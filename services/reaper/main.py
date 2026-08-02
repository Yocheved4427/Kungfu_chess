from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Optional

import redis.asyncio as redis
from aiokafka import AIOKafkaProducer
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Kung Fu Chess -- Reaper Service (services/reaper)
# ---------------------------------------------------------------------------
# Cleanup worker for rooms services/game_server/main.py leaks when both
# players disconnect WITHOUT a natural GameOverEvent -- the abnormal-exit
# case that service's own graceful _handle_game_over never runs for
# (Redis' room_count/room->server pointer stay claimed forever, and
# nothing ever tells Postgres the game ended). This is that safety net,
# not a replacement for the graceful path -- a room that ends normally
# is already fully cleaned up by the Game Server itself before this
# service would ever see it (see game_server's own `rooms:active`/
# heartbeat/meta cleanup in _handle_game_over).
#
# Detection: every Game Server refreshes `room:{room_id}:heartbeat`
# (a unix timestamp) at its own 10Hz broadcast cadence, for as long as
# at least one player is connected AND the game hasn't ended. Once both
# players disconnect mid-game, that refresh simply stops -- there is no
# separate "abnormal disconnect" signal anywhere; a heartbeat older than
# REAPER_TTL_S *is* the signal. `rooms:active` (a Redis SET) is this
# service's only enumeration source, so it never has to SCAN the whole
# keyspace.
#
# On finding a stale room, this service:
#   1. "Notifies the Allocator/Registry to free up container capacity"
#      by performing the EXACT SAME Redis mutations the owning Game
#      Server's own graceful cleanup would have (DECR gs:{id}:room_count,
#      DELETE room:{room_id}:game_server) -- decision 10's Allocator has
#      no cache of its own, it always reads these keys live, so writing
#      them IS notifying it; no new HTTP endpoint needed or added.
#   2. Publishes an "unattended closure" event to the SAME `game_ended`
#      Kafka topic and schema services/event_consumer/main.py already
#      consumes for a normal game end (winner_id=None, zero ELO deltas
#      -- an abandoned game has no legitimate winner to credit) -- no
#      changes needed to event_consumer at all.
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reaper")

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
GAME_ENDED_TOPIC = os.environ.get("GAME_ENDED_TOPIC", "game_ended")

REAPER_INTERVAL_S = float(os.environ.get("REAPER_INTERVAL_S", "30"))  # requirement 1
REAPER_TTL_S = float(os.environ.get("REAPER_TTL_S", "60"))            # requirement 2

ROOMS_ACTIVE_SET = "rooms:active"


def _heartbeat_key(room_id: str) -> str:
    return f"room:{room_id}:heartbeat"


def _meta_key(room_id: str) -> str:
    return f"room:{room_id}:meta"


class AppState:
    redis: redis.Redis
    kafka_producer: AIOKafkaProducer
    kafka_ready: bool = False
    scan_task: asyncio.Task
    last_scan_at: Optional[float] = None
    last_scan_reaped: int = 0
    total_reaped: int = 0


state = AppState()


# ---------------------------------------------------------------------------
# The scan loop (requirement 1: fixed clock interval)
# ---------------------------------------------------------------------------

async def _scan_loop() -> None:
    while True:
        await asyncio.sleep(REAPER_INTERVAL_S)
        try:
            await _scan_once()
        except Exception:  # noqa: BLE001 -- one bad scan must not kill the loop forever
            logger.exception("Reaper scan failed; will retry in %.0fs", REAPER_INTERVAL_S)


async def _scan_once() -> None:
    """One pass over every room this fleet believes is active (requirement
    2: stale heartbeats / abandoned states exceeding REAPER_TTL_S)."""
    now = time.time()
    room_ids = await state.redis.smembers(ROOMS_ACTIVE_SET)

    reaped = 0
    for room_id in room_ids:
        heartbeat_raw = await state.redis.get(_heartbeat_key(room_id))
        if heartbeat_raw is None:
            age: Optional[float] = None
            stale = True  # a room in rooms:active with no heartbeat at all is unambiguously abandoned
        else:
            age = now - float(heartbeat_raw)
            stale = age > REAPER_TTL_S

        if stale:
            await _reap_room(room_id, age)
            reaped += 1

    state.last_scan_at = now
    state.last_scan_reaped = reaped
    state.total_reaped += reaped
    if reaped:
        logger.info("Reaper scan: reaped %d stale room(s) out of %d active", reaped, len(room_ids))
    else:
        logger.debug("Reaper scan: %d active room(s), none stale", len(room_ids))


# ---------------------------------------------------------------------------
# Reaping one room (requirements 3 and 4)
# ---------------------------------------------------------------------------

async def _reap_room(room_id: str, age: Optional[float]) -> None:
    age_desc = f"{age:.1f}s" if age is not None else "missing"
    logger.warning("Reaping abandoned room %r (heartbeat age=%s, ttl=%.0fs)", room_id, age_desc, REAPER_TTL_S)

    meta = await state.redis.hgetall(_meta_key(room_id))
    game_server_id = await state.redis.get(f"room:{room_id}:game_server")

    # Requirement 3: free the owning Game Server's claimed capacity --
    # see this module's own docstring for why this is "notifying the
    # Allocator" without a new HTTP call.
    if game_server_id:
        await state.redis.decr(f"gs:{game_server_id}:room_count")
    await state.redis.delete(f"room:{room_id}:game_server")
    await state.redis.delete(_heartbeat_key(room_id))
    await state.redis.delete(_meta_key(room_id))
    await state.redis.srem(ROOMS_ACTIVE_SET, room_id)

    # Requirement 4: unattended closure event, same topic/schema as a
    # normal game end.
    payload = {
        "game_id": room_id,
        "white_player_id": int(meta.get("white_player_id", 0) or 0),
        "black_player_id": int(meta.get("black_player_id", 0) or 0),
        "winner_id": None,
        "white_elo_delta": 0,
        "black_elo_delta": 0,
        "moves": [],
        "ended_at": time.time(),
        "reason": "abandoned",  # extra field -- event_consumer reads named keys only, ignores this
    }
    await state.kafka_producer.send_and_wait(GAME_ENDED_TOPIC, json.dumps(payload).encode("utf-8"))
    logger.info("Published unattended game_ended for room %r: %s", room_id, payload)


# ---------------------------------------------------------------------------
# FastAPI app (health/observability only -- the scan loop above is the
# actual service; nothing here is on its critical path)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    state.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    await state.redis.ping()

    state.kafka_producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
    await state.kafka_producer.start()
    state.kafka_ready = True

    state.scan_task = asyncio.create_task(_scan_loop())
    logger.info(
        "Reaper started: interval=%.0fs ttl=%.0fs redis=%s:%d kafka=%s",
        REAPER_INTERVAL_S, REAPER_TTL_S, REDIS_HOST, REDIS_PORT, KAFKA_BOOTSTRAP_SERVERS,
    )
    try:
        yield
    finally:
        state.scan_task.cancel()
        state.kafka_ready = False
        await state.kafka_producer.stop()
        await state.redis.aclose()


app = FastAPI(title="Kung Fu Chess -- Reaper", lifespan=lifespan)


@app.get("/health")
async def health() -> JSONResponse:
    checks = {"redis": False, "kafka": state.kafka_ready}
    try:
        checks["redis"] = bool(await state.redis.ping())
    except Exception as e:  # noqa: BLE001
        logger.warning("Redis health check failed: %s", e)
    healthy = all(checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "checks": checks,
            "interval_s": REAPER_INTERVAL_S,
            "ttl_s": REAPER_TTL_S,
            "last_scan_at": state.last_scan_at,
            "last_scan_reaped": state.last_scan_reaped,
            "total_reaped": state.total_reaped,
        },
    )
