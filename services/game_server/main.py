from __future__ import annotations

import logging
import os
import socket
from contextlib import asynccontextmanager
from typing import Tuple

import redis.asyncio as redis
from aiokafka import AIOKafkaProducer
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from shared.models.cell import Cell

from services.game_server.domain import (
    InvalidJoinRequestError,
    InvalidMoveRequestError,
    PlayerMeta,
    RoomError,
    color_from_wire,
)
from services.game_server.room_service import GAME_SERVERS_SET, RoomService

# ---------------------------------------------------------------------------
# Kung Fu Chess -- Game Server controller (services/game_server/main.py)
# ---------------------------------------------------------------------------
# The "Controller" layer, and ONLY that: FastAPI wiring, wire-format
# parsing/validation, and translating RoomError subclasses into clean
# WebSocket error messages. No business logic lives here -- every
# decision about rooms, moves, or pausing is made by RoomService
# (room_service.py), which this module never bypasses by reaching into
# its internals directly.
#
# Server_Design.md decisions 2, 4, 7, 10, 11: hosts the actual
# RealTimeArbiter + GameEngine (UNCHANGED from server/game/real_time_arbiter.py
# and engine/game.py -- no rewrite, per decision 7) for every room this
# container owns. Clients connect DIRECTLY here after Matchmaking's
# redirect (decision 2) -- this service never talks to the Gateway.
#
# Simplifications versus the full production design, called out
# explicitly rather than silently:
#   * Decision 4 calls for full cell-diff broadcasts; this sends a full
#     board snapshot at the same 10Hz cadence (the rate reduction is
#     real, the diff-encoding optimization on top of it is not).
#   * A room here starts as soon as its FIRST connection arrives (rather
#     than waiting for exactly two, per RoomService.MAX_PLAYERS) so a
#     single WebSocket client is enough to exercise the real engine
#     end-to-end for local testing.
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("game_server")

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
GAME_ENDED_TOPIC = os.environ.get("GAME_ENDED_TOPIC", "game_ended")

GAME_SERVER_ID = os.environ.get("GAME_SERVER_ID", socket.gethostname())
GAME_SERVER_HOST = os.environ.get("GAME_SERVER_HOST", GAME_SERVER_ID)
GAME_SERVER_PORT = int(os.environ.get("GAME_SERVER_PORT", "8001"))
PAUSE_TTL_S = int(os.environ.get("PAUSE_TTL_S", str(24 * 60 * 60)))  # requirement 1: 24 hours


class AppState:
    redis: redis.Redis
    kafka_producer: AIOKafkaProducer
    kafka_ready: bool = False
    room_service: RoomService


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    await state.redis.sadd(GAME_SERVERS_SET, GAME_SERVER_ID)
    await state.redis.set(f"gs:{GAME_SERVER_ID}:host", GAME_SERVER_HOST)
    await state.redis.set(f"gs:{GAME_SERVER_ID}:port", GAME_SERVER_PORT)
    await state.redis.set(f"gs:{GAME_SERVER_ID}:status", "available")
    await state.redis.set(f"gs:{GAME_SERVER_ID}:room_count", 0)
    logger.info("Registered game server %r (%s:%d) in Redis", GAME_SERVER_ID, GAME_SERVER_HOST, GAME_SERVER_PORT)

    state.kafka_producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
    await state.kafka_producer.start()
    state.kafka_ready = True
    logger.info("Kafka producer connected to %s", KAFKA_BOOTSTRAP_SERVERS)

    state.room_service = RoomService(
        redis_client=state.redis,
        kafka_producer=state.kafka_producer,
        game_server_id=GAME_SERVER_ID,
        game_ended_topic=GAME_ENDED_TOPIC,
        pause_ttl_s=PAUSE_TTL_S,
    )
    try:
        yield
    finally:
        state.kafka_ready = False
        await state.kafka_producer.stop()
        await state.redis.set(f"gs:{GAME_SERVER_ID}:status", "offline")
        await state.redis.aclose()


app = FastAPI(title=f"Kung Fu Chess -- Game Server ({GAME_SERVER_ID})", lifespan=lifespan)


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
            "server_id": GAME_SERVER_ID,
            "rooms": len(state.room_service.rooms),
            "checks": checks,
        },
    )


# ---------------------------------------------------------------------------
# Wire-format parsing (Gatekeeper Pattern): every untrusted value crossing
# the WebSocket boundary is validated HERE, once, and turned into either a
# real domain object or a RoomError subclass -- nothing downstream ever
# sees a raw, unvalidated string/dict, and nothing downstream needs its
# own defensive parsing.
# ---------------------------------------------------------------------------

def _parse_join_params(websocket: WebSocket) -> Tuple[str, PlayerMeta]:
    username = websocket.query_params.get("username") or f"anon-{id(websocket):x}"
    raw_user_id = websocket.query_params.get("user_id", "0")
    raw_elo = websocket.query_params.get("elo", "1200")
    raw_color = websocket.query_params.get("color", "white")

    try:
        user_id = int(raw_user_id)
        elo = int(raw_elo)
    except ValueError as exc:
        raise InvalidJoinRequestError(
            f"user_id/elo must be integers (got user_id={raw_user_id!r}, elo={raw_elo!r})"
        ) from exc

    color = color_from_wire(raw_color)  # raises InvalidColorError (a RoomError)
    return username, PlayerMeta(user_id=user_id, elo=elo, color=color)


def _parse_move_payload(message: dict) -> Tuple[Cell, Cell]:
    try:
        from_cell = Cell(message["from"]["row"], message["from"]["col"])
        to_cell = Cell(message["to"]["row"], message["to"]["col"])
    except (KeyError, TypeError) as exc:
        raise InvalidMoveRequestError(f"malformed move payload: {message!r}") from exc
    return from_cell, to_cell


# ---------------------------------------------------------------------------
# Client <-> Game Server WebSocket (decision 2: direct, post-redirect;
# decision 6: JSON)
# ---------------------------------------------------------------------------

@app.websocket("/ws/{room_id}")
async def ws_room(websocket: WebSocket, room_id: str) -> None:
    await websocket.accept()

    try:
        username, meta = _parse_join_params(websocket)
    except RoomError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=4400)
        return

    try:
        room = await state.room_service.join_room(room_id, username, meta, websocket)
    except RoomError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=4409)
        return

    logger.info(
        "Room %r: %r connected as %s (%d players now)",
        room_id, username, meta.color.value, len(room.connections),
    )
    await websocket.send_json(
        {"type": "joined", "room_id": room_id, "color": meta.color.value, "server_id": GAME_SERVER_ID}
    )

    try:
        while True:
            message = await websocket.receive_json()
            action = message.get("action")

            if action == "move":
                try:
                    from_cell, to_cell = _parse_move_payload(message)
                    legality = state.room_service.submit_move(room, from_cell, to_cell)
                except RoomError as exc:
                    await websocket.send_json({"type": "error", "message": str(exc)})
                    continue
                await websocket.send_json({"type": "move_ack", "legality": legality.name})

            elif action == "pause":
                # Either player may pause unilaterally -- "explicitly
                # leaves with the option to return later" (spec) is a
                # whole-room action, not a per-player one, same as this
                # engine has no turn structure to pause "your side" of.
                try:
                    await state.room_service.pause_room(room)
                except RoomError as exc:
                    # A rejected pause (e.g. already paused) is real,
                    # user-facing feedback now -- not a silent no-op the
                    # client has no way to notice.
                    await websocket.send_json({"type": "error", "message": str(exc)})
                    continue
                return  # pause_room already closed every connection, this one included

            else:
                await websocket.send_json({"type": "error", "message": f"unknown action {action!r}"})
    except WebSocketDisconnect:
        logger.info("Room %r: %r disconnected", room_id, username)
    finally:
        await state.room_service.leave_room(room, username)
