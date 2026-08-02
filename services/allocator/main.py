from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Kung Fu Chess -- Game Allocator service (services/allocator)
# ---------------------------------------------------------------------------
# Server_Design.md decision 10: split out of Matchmaking because room
# placement is bin-packing (which Game Server has room for one more),
# not queue-matching. Entirely stateless compute -- every fact it needs
# (each Game Server's current room count and drain status, keyed
# gs:{id}:*) lives in Redis, written by the Game Server containers
# themselves (see services/game_server/main.py's startup registration
# and shutdown/game-end decrements).
#
# Uses exactly the two atomic Redis primitives decision 10 specifies,
# instead of a general-purpose distributed lock:
#   * INCR gs:{id}:room_count -- claim capacity first, verify after;
#     DECR + retry a different server if it turns out to be full. Worst
#     case one server overshoots by exactly 1 for the instant between
#     INCR and the correcting DECR -- never stuck over capacity.
#   * SET room:{room_id}:game_server {id} NX -- first allocator instance
#     to win the assignment; a racing retry for the same room_id reads
#     the existing assignment back instead of creating a conflicting one.
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("allocator")

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
# Production value is 5,000 (decision 7); a small local-dev default keeps
# the "server is full, try another" retry path exercisable by hand.
MAX_ROOMS_PER_CONTAINER = int(os.environ.get("MAX_ROOMS_PER_CONTAINER", "100"))

GAME_SERVERS_SET = "gs:all"


class AppState:
    redis: redis.Redis


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    logger.info("Allocator ready (redis client), MAX_ROOMS_PER_CONTAINER=%d", MAX_ROOMS_PER_CONTAINER)
    try:
        yield
    finally:
        await state.redis.aclose()


app = FastAPI(title="Kung Fu Chess -- Allocator", lifespan=lifespan)


@app.get("/health")
async def health() -> JSONResponse:
    try:
        ok = bool(await state.redis.ping())
    except Exception as e:  # noqa: BLE001
        logger.warning("Redis health check failed: %s", e)
        ok = False
    return JSONResponse(status_code=200 if ok else 503, content={"status": "ok" if ok else "degraded"})


async def _server_info(server_id: str) -> dict | None:
    host, port, status = await state.redis.mget(
        f"gs:{server_id}:host", f"gs:{server_id}:port", f"gs:{server_id}:status"
    )
    if host is None or port is None:
        return None
    return {"id": server_id, "host": host, "port": int(port), "status": status or "available"}


async def _least_loaded_candidates() -> list[str]:
    """Every registered, non-draining Game Server id, least-loaded first."""
    ids = await state.redis.smembers(GAME_SERVERS_SET)
    candidates = []
    for server_id in ids:
        status = await state.redis.get(f"gs:{server_id}:status")
        if status == "draining":
            continue  # decision 9: a draining server never gets new rooms
        room_count = int(await state.redis.get(f"gs:{server_id}:room_count") or 0)
        candidates.append((room_count, server_id))
    candidates.sort(key=lambda pair: pair[0])
    return [server_id for _, server_id in candidates]


class AllocateRequest(BaseModel):
    room_id: str


@app.post("/allocate")
async def allocate(req: AllocateRequest) -> dict:
    candidates = await _least_loaded_candidates()
    if not candidates:
        raise HTTPException(503, "no Game Server instances are registered")

    for server_id in candidates:
        room_count = await state.redis.incr(f"gs:{server_id}:room_count")
        if room_count > MAX_ROOMS_PER_CONTAINER:
            await state.redis.decr(f"gs:{server_id}:room_count")
            continue  # this one's full -- try the next-least-loaded candidate

        won = await state.redis.set(f"room:{req.room_id}:game_server", server_id, nx=True)
        if not won:
            # Someone else already assigned this room_id (a retried
            # request) -- give back the capacity we just claimed and
            # report the assignment that actually won instead.
            await state.redis.decr(f"gs:{server_id}:room_count")
            existing_id = await state.redis.get(f"room:{req.room_id}:game_server")
            info = await _server_info(existing_id)
            if info is None:
                raise HTTPException(500, "race lost to an assignment that no longer exists")
            return {"game_server_id": info["id"], "host": info["host"], "port": info["port"]}

        info = await _server_info(server_id)
        logger.info("Placed room %r on game server %r (room_count=%d)", req.room_id, server_id, room_count)
        return {"game_server_id": info["id"], "host": info["host"], "port": info["port"]}

    raise HTTPException(503, "every registered Game Server is at capacity")
