from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from server.services.matchmaking_service import MatchmakingService

# ---------------------------------------------------------------------------
# Kung Fu Chess -- Matchmaking service (services/matchmaking)
# ---------------------------------------------------------------------------
# Server_Design.md decision 10: the *global* view of who's waiting, backed
# by Redis so it's shared across every Matchmaking replica (not an
# in-process list, per server/services/matchmaking_service.py's own
# module docstring). The ELO-window-widening pairing algorithm itself is
# reused UNCHANGED from that module -- MatchmakingService is stateless
# compute, reconstructed fresh from Redis's current queue snapshot on
# every request, then thrown away; Redis (mm:queue / mm:elo) is the only
# durable state, matching the server-types table's
# "Compute: no. Registry/queue: yes, in Redis" split.
#
# Once a pair is found, this service calls out to services/allocator/
# (decision 10) to place the new room on a Game Server, then stores the
# redirect (game_server host/port + room_id) under mm:result:{username}
# for both matched players -- services/gateway/'s /matchmaking/result
# proxy (and its WebSocket poll loop) reads it from there.
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("matchmaking")

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
ALLOCATOR_URL = os.environ.get("ALLOCATOR_URL", "http://allocator:8020")

QUEUE_KEY = "mm:queue"           # sorted set: username -> queued_at (unix seconds)
ELO_KEY = "mm:elo"               # hash: username -> elo_rating
RESULT_PREFIX = "mm:result:"     # string per username, JSON, short TTL
RESULT_TTL_S = 60


class AppState:
    redis: redis.Redis
    http: httpx.AsyncClient


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    state.http = httpx.AsyncClient(timeout=5.0)
    logger.info("Matchmaking ready (redis client + http client)")
    try:
        yield
    finally:
        await state.http.aclose()
        await state.redis.aclose()


app = FastAPI(title="Kung Fu Chess -- Matchmaking", lifespan=lifespan)


@app.get("/health")
async def health() -> JSONResponse:
    try:
        ok = bool(await state.redis.ping())
    except Exception as e:  # noqa: BLE001
        logger.warning("Redis health check failed: %s", e)
        ok = False
    return JSONResponse(status_code=200 if ok else 503, content={"status": "ok" if ok else "degraded"})


class EnqueueRequest(BaseModel):
    username: str
    elo_rating: int


async def _load_service() -> MatchmakingService:
    """Rebuild a fresh, in-memory MatchmakingService from Redis's current
    queue snapshot -- the exact same ELO-window pairing algorithm as
    server/services/matchmaking_service.py, just fed from durable, shared
    storage instead of a list that lives only in this one process.
    """
    svc = MatchmakingService()
    members = await state.redis.zrange(QUEUE_KEY, 0, -1, withscores=True)
    if members:
        usernames = [username for username, _ in members]
        elos = await state.redis.hmget(ELO_KEY, usernames)
        for (username, queued_at), elo in zip(members, elos):
            svc.enqueue(username, int(elo or 1200), queued_at=queued_at)
    return svc


async def _place_room(player_a: str, player_b: str) -> dict:
    """Ask services/allocator/ to place a new room for this pairing
    (decision 10), then hand the redirect back to both matched players
    via mm:result:{username} for services/gateway/ to relay.
    """
    room_id = uuid.uuid4().hex[:8]
    resp = await state.http.post(f"{ALLOCATOR_URL}/allocate", json={"room_id": room_id})
    resp.raise_for_status()
    allocation = resp.json()

    result = {
        "status": "matched",
        "room_id": room_id,
        "opponent": None,  # filled in per-player below
        "game_server": {"host": allocation["host"], "port": allocation["port"]},
    }
    for username, opponent in ((player_a, player_b), (player_b, player_a)):
        await state.redis.setex(
            f"{RESULT_PREFIX}{username}", RESULT_TTL_S, json.dumps({**result, "opponent": opponent})
        )
    logger.info("Matched %r vs %r -> room %r on %s", player_a, player_b, room_id, allocation)
    return result


@app.post("/enqueue")
async def enqueue(req: EnqueueRequest) -> dict:
    now = time.time()
    # NX: don't reset an already-queued player's wait time on a repeat call.
    await state.redis.zadd(QUEUE_KEY, {req.username: now}, nx=True)
    await state.redis.hset(ELO_KEY, req.username, req.elo_rating)

    matched_this_call = False
    svc = await _load_service()
    while True:
        pairing = svc.find_match(current_time=now)
        if pairing is None:
            break
        a, b = pairing.player_a.username, pairing.player_b.username
        await state.redis.zrem(QUEUE_KEY, a, b)
        await state.redis.hdel(ELO_KEY, a, b)
        await _place_room(a, b)
        if req.username in (a, b):
            matched_this_call = True

    if matched_this_call:
        raw = await state.redis.get(f"{RESULT_PREFIX}{req.username}")
        return json.loads(raw) if raw else {"status": "queued"}
    return {"status": "queued"}


@app.get("/result/{username}")
async def result(username: str) -> dict:
    raw = await state.redis.get(f"{RESULT_PREFIX}{username}")
    if raw is not None:
        return json.loads(raw)
    if await state.redis.zscore(QUEUE_KEY, username) is not None:
        return {"status": "queued"}
    return {"status": "not_found"}
