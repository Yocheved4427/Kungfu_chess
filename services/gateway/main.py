from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager

import asyncpg
import bcrypt
import httpx
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Kung Fu Chess -- Gateway / Auth service (services/gateway)
# ---------------------------------------------------------------------------
# Server_Design.md decisions 1, 2, 5, 10: the only internet-facing tier in
# this local-dev stack. Owns:
#   * Register/Login against PostgreSQL (asyncpg) -- the same
#     bcrypt-hashed-password flow as server/services/auth_service.py's
#     AuthService, ported from sqlite3 to asyncpg.
#   * A Redis-backed session token (decision: holds no per-player game
#     state itself -- "Stateful? No (signed session token)" per the
#     server-types table).
#   * A WebSocket endpoint for the client<->Gateway leg (decision 5), and
#     a thin proxy to services/matchmaking/ for "join the queue" /
#     "where do I connect" requests (decision 2: matchmaking replies with
#     a direct redirect to a Game Server, not a proxied connection).
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway")

POSTGRES_URI = os.environ.get(
    "POSTGRES_URI",
    "postgresql://kungfu:kungfu_dev_password@postgres:5432/kungfu_chess",
)
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
MATCHMAKING_URL = os.environ.get("MATCHMAKING_URL", "http://matchmaking:8010")
SESSION_TTL_S = int(os.environ.get("SESSION_TTL_S", "3600"))


class AppState:
    pg_pool: asyncpg.Pool
    redis: redis.Redis
    http: httpx.AsyncClient


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.pg_pool = await asyncpg.create_pool(POSTGRES_URI, min_size=1, max_size=10)
    state.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    state.http = httpx.AsyncClient(timeout=5.0)
    logger.info("Gateway ready (postgres pool + redis client + http client)")
    try:
        yield
    finally:
        await state.http.aclose()
        await state.redis.aclose()
        await state.pg_pool.close()


app = FastAPI(title="Kung Fu Chess -- Gateway", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> JSONResponse:
    checks = {"redis": False, "postgres": False}
    try:
        checks["redis"] = bool(await state.redis.ping())
    except Exception as e:  # noqa: BLE001 -- health check reports, never raises
        logger.warning("Redis health check failed: %s", e)
    try:
        async with state.pg_pool.acquire() as conn:
            checks["postgres"] = (await conn.fetchval("SELECT 1")) == 1
    except Exception as e:  # noqa: BLE001
        logger.warning("Postgres health check failed: %s", e)

    healthy = all(checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )


# ---------------------------------------------------------------------------
# Auth (decision: Register/Login against the DB cluster, unchanged
# conceptually from server/services/auth_service.py's AuthService)
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


def _is_present(value: str) -> bool:
    return bool(value) and bool(value.strip())


@app.post("/auth/register")
async def register(req: RegisterRequest) -> dict:
    if not _is_present(req.username) or not _is_present(req.password):
        raise HTTPException(400, "username and password are required")

    password_hash = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    async with state.pg_pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                "INSERT INTO users (username, password_hash) VALUES ($1, $2) "
                "RETURNING user_id, username, elo_rating",
                req.username,
                password_hash,
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "username already taken")

    logger.info("Registered user %r (user_id=%d)", row["username"], row["user_id"])
    return dict(row)


@app.post("/auth/login")
async def login(req: LoginRequest) -> dict:
    if not _is_present(req.username) or not _is_present(req.password):
        raise HTTPException(400, "username and password are required")

    async with state.pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, username, password_hash, elo_rating FROM users WHERE username = $1",
            req.username,
        )

    if row is None or not bcrypt.checkpw(req.password.encode("utf-8"), row["password_hash"].encode("utf-8")):
        # Deliberately not distinguished (unknown user vs wrong password) --
        # same rationale as AuthService.login's own docstring.
        raise HTTPException(401, "invalid credentials")

    token = uuid.uuid4().hex
    await state.redis.setex(f"session:{token}", SESSION_TTL_S, row["username"])
    logger.info("Logged in %r (user_id=%d)", row["username"], row["user_id"])
    return {
        "token": token,
        "user_id": row["user_id"],
        "username": row["username"],
        "elo_rating": row["elo_rating"],
    }


async def _username_for_token(token: str) -> str:
    username = await state.redis.get(f"session:{token}")
    if username is None:
        raise HTTPException(401, "invalid or expired session token")
    return username


# ---------------------------------------------------------------------------
# Matchmaking proxy (decision 2: Gateway forwards "I want to play" to
# Matchmaking; it never proxies gameplay traffic itself)
# ---------------------------------------------------------------------------

class QueueRequest(BaseModel):
    token: str


@app.post("/matchmaking/queue")
async def queue_for_match(req: QueueRequest) -> dict:
    username = await _username_for_token(req.token)
    async with state.pg_pool.acquire() as conn:
        elo_rating = await conn.fetchval("SELECT elo_rating FROM users WHERE username = $1", username)

    resp = await state.http.post(
        f"{MATCHMAKING_URL}/enqueue", json={"username": username, "elo_rating": elo_rating}
    )
    resp.raise_for_status()
    return resp.json()


@app.get("/matchmaking/result")
async def matchmaking_result(token: str) -> dict:
    username = await _username_for_token(token)
    resp = await state.http.get(f"{MATCHMAKING_URL}/result/{username}")
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Client <-> Gateway WebSocket (decision 5) -- auth/matchmaking traffic
# only; once matched, the client reconnects DIRECTLY to the assigned
# Game Server (decision 2), not through this socket.
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4401)
        return
    try:
        username = await _username_for_token(token)
    except HTTPException:
        await ws.close(code=4401)
        return

    await ws.accept()
    logger.info("WS connected: %r", username)
    try:
        while True:
            message = await ws.receive_json()
            action = message.get("action")

            if action == "queue":
                async with state.pg_pool.acquire() as conn:
                    elo_rating = await conn.fetchval(
                        "SELECT elo_rating FROM users WHERE username = $1", username
                    )
                resp = await state.http.post(
                    f"{MATCHMAKING_URL}/enqueue", json={"username": username, "elo_rating": elo_rating}
                )
                await ws.send_json({"type": "queue_ack", **resp.json()})

                # Poll matchmaking for a result and push it the instant
                # it's ready, rather than making the client poll itself.
                asyncio.create_task(_poll_and_push_match(ws, username))
            else:
                await ws.send_json({"type": "error", "message": f"unknown action {action!r}"})
    except WebSocketDisconnect:
        logger.info("WS disconnected: %r", username)


async def _poll_and_push_match(ws: WebSocket, username: str, timeout_s: float = 30.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        resp = await state.http.get(f"{MATCHMAKING_URL}/result/{username}")
        payload = resp.json()
        if payload.get("status") == "matched":
            try:
                await ws.send_json({"type": "matched", **payload})
            except RuntimeError:
                pass  # socket already closed client-side
            return
        await asyncio.sleep(0.5)
