from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Dict, Optional

import redis.asyncio as redis
from aiokafka import AIOKafkaProducer
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from shared.models.board import AbstractBoard, TextBoard
from shared.models.cell import Cell
from engine.game import GameEngine
from engine.game_state import GameState
from server.game.real_time_arbiter import RealTimeArbiter
from ui.events import GameEvent, GameOverEvent, Observer
from ui.game_factory import STANDARD_BOARD_ROWS

# ---------------------------------------------------------------------------
# Kung Fu Chess -- Game Server service (services/game_server)
# ---------------------------------------------------------------------------
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
#     real, the diff-encoding optimization on top of it is not -- that's
#     a pure wire-format change, safe to add later without touching the
#     tick loop below).
#   * A room here starts as soon as its FIRST connection arrives (rather
#     than waiting for exactly two, per RoomService.MAX_PLAYERS) so a
#     single WebSocket client is enough to exercise the real engine
#     end-to-end for local testing -- see the instructions for how to
#     drive both colours from one connection.
#
# On every GameOverEvent (decision 11), this service computes both
# players' ELO deltas itself (it already knows both ratings, passed in
# as connection query params -- in the full system these would come from
# Matchmaking at pairing time) and publishes one "game_ended" event to
# Kafka, then immediately decrements its own room count in Redis
# (gs:{id}:room_count) so services/allocator/ sees the freed capacity --
# never touching Postgres directly (decision 3).
#
# Room heartbeat/meta (for services/reaper/main.py): alongside the
# allocator-owned `room:{room_id}:game_server` pointer, this service
# maintains `rooms:active` (a set of every room_id it currently owns),
# `room:{room_id}:heartbeat` (refreshed every broadcast tick -- 10Hz),
# and `room:{room_id}:meta` (player_id/elo per colour, written as each
# player joins). If both players disconnect before a natural
# GameOverEvent, _broadcast_loop's own `while room.connections:` guard
# stops refreshing the heartbeat -- there is deliberately no separate
# "abnormal disconnect" code path; a stale heartbeat *is* the signal,
# and reaping it (freeing gs:{id}:room_count, publishing an
# unattended-closure event to Kafka) is entirely the Reaper's job, not
# this service's.
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

GAME_SERVERS_SET = "gs:all"
ROOMS_ACTIVE_SET = "rooms:active"
TICK_INTERVAL_S = 0.03    # 30ms simulation tick (unchanged from RealTimeArbiter's own cadence)
BROADCAST_INTERVAL_S = 0.1  # 10Hz state broadcast (decision 4)
ELO_K_FACTOR = 32


def _heartbeat_key(room_id: str) -> str:
    return f"room:{room_id}:heartbeat"


def _meta_key(room_id: str) -> str:
    return f"room:{room_id}:meta"


class AppState:
    redis: redis.Redis
    kafka_producer: AIOKafkaProducer
    kafka_ready: bool = False


state = AppState()


@dataclass
class RoomGame:
    room_id: str
    board: AbstractBoard
    state: GameState
    engine: GameEngine
    arbiter: RealTimeArbiter
    connections: Dict[str, WebSocket] = field(default_factory=dict)
    player_meta: Dict[str, dict] = field(default_factory=dict)  # username -> {user_id, elo, color}
    pending_events: list = field(default_factory=list)
    ended: bool = False


ROOMS: Dict[str, RoomGame] = {}


class _RoomObserver(Observer):
    """Bridges GameEngine's synchronous Observer callback into this
    room's event buffer (flushed at the 10Hz broadcast cadence) and, on
    GameOverEvent, schedules the Kafka publish immediately rather than
    waiting for the next broadcast tick.
    """

    def __init__(self, room: RoomGame) -> None:
        self._room = room

    def on_event(self, event: GameEvent) -> None:
        self._room.pending_events.append(event.to_dict())
        if isinstance(event, GameOverEvent):
            asyncio.create_task(_handle_game_over(self._room, event))


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
        content={"status": "ok" if healthy else "degraded", "server_id": GAME_SERVER_ID, "rooms": len(ROOMS), "checks": checks},
    )


# ---------------------------------------------------------------------------
# Room lifecycle
# ---------------------------------------------------------------------------

def _create_room(room_id: str) -> RoomGame:
    board = TextBoard(STANDARD_BOARD_ROWS)
    game_state = GameState(board=board)
    engine = GameEngine(board)
    arbiter = RealTimeArbiter(engine, game_state)
    room = RoomGame(room_id=room_id, board=board, state=game_state, engine=engine, arbiter=arbiter)
    arbiter.add_observer(_RoomObserver(room))
    asyncio.create_task(_tick_loop(room))
    asyncio.create_task(_broadcast_loop(room))
    return room


async def _tick_loop(room: RoomGame) -> None:
    while room.connections and not room.state.game_over:
        await asyncio.sleep(TICK_INTERVAL_S)
        if not room.connections:
            break
        room.arbiter.advance(int(TICK_INTERVAL_S * 1000))


async def _broadcast_loop(room: RoomGame) -> None:
    while room.connections:
        await asyncio.sleep(BROADCAST_INTERVAL_S)
        if not room.connections:
            break
        # The heartbeat services/reaper/main.py polls for -- refreshed
        # every tick this loop actually runs. Once both players
        # disconnect, `while room.connections:` above stops this loop
        # (and thus this refresh) on its own -- no separate signal
        # needed for "abandoned".
        await state.redis.set(_heartbeat_key(room.room_id), time.time())
        snapshot = {
            "type": "snapshot",
            "current_time": room.state.current_time,
            "board": room.board.get_rows(),
            "game_over": room.state.game_over,
            "winner": room.state.winner.value if room.state.winner is not None else None,
            "events": room.pending_events,
        }
        room.pending_events = []
        dead = []
        for username, ws in room.connections.items():
            try:
                await ws.send_json(snapshot)
            except Exception:  # noqa: BLE001 -- a broken socket is cleaned up below, not raised
                dead.append(username)
        for username in dead:
            room.connections.pop(username, None)
            room.player_meta.pop(username, None)


def _elo_deltas(white_elo: int, black_elo: int, winner_color: Optional[str]) -> tuple[int, int]:
    """Standard ELO delta for both players -- computed here (not stored
    anywhere mid-game) because decision 11 requires the "game ended"
    Kafka event to carry commutative DELTAS, never absolute ratings.
    """
    expected_white = 1 / (1 + 10 ** ((black_elo - white_elo) / 400))
    expected_black = 1 - expected_white
    score_white = 1.0 if winner_color == "w" else 0.0 if winner_color == "b" else 0.5
    score_black = 1.0 - score_white
    return (
        round(ELO_K_FACTOR * (score_white - expected_white)),
        round(ELO_K_FACTOR * (score_black - expected_black)),
    )


async def _handle_game_over(room: RoomGame, event: GameOverEvent) -> None:
    if room.ended:
        return
    room.ended = True

    white = next((meta for meta in room.player_meta.values() if meta["color"] == "white"), None)
    black = next((meta for meta in room.player_meta.values() if meta["color"] == "black"), None)
    winner_color = event.winner.value if event.winner is not None else None

    white_delta, black_delta = (
        _elo_deltas(white["elo"], black["elo"], winner_color) if white and black else (0, 0)
    )
    winner_user_id = None
    if winner_color == "w" and white:
        winner_user_id = white["user_id"]
    elif winner_color == "b" and black:
        winner_user_id = black["user_id"]

    payload = {
        "game_id": room.room_id,
        "white_player_id": white["user_id"] if white else 0,
        "black_player_id": black["user_id"] if black else 0,
        "winner_id": winner_user_id,
        "white_elo_delta": white_delta,
        "black_elo_delta": black_delta,
        "moves": [],
        "ended_at": time.time(),
    }
    await state.kafka_producer.send_and_wait(GAME_ENDED_TOPIC, json.dumps(payload).encode("utf-8"))
    logger.info("Published game_ended for room %r: %s", room.room_id, payload)

    await state.redis.decr(f"gs:{GAME_SERVER_ID}:room_count")
    await state.redis.delete(f"room:{room.room_id}:game_server")
    # A natural game-over is not what the Reaper exists for -- clean up
    # its bookkeeping ourselves so a gracefully-ended room never shows
    # up in a later reaper scan (rooms:active is the reaper's only
    # enumeration source; leaving a stale entry there would make it try
    # to reap an already-finished room).
    await state.redis.srem(ROOMS_ACTIVE_SET, room.room_id)
    await state.redis.delete(_heartbeat_key(room.room_id))
    await state.redis.delete(_meta_key(room.room_id))


# ---------------------------------------------------------------------------
# Client <-> Game Server WebSocket (decision 2: direct, post-redirect;
# decision 6: JSON)
# ---------------------------------------------------------------------------

@app.websocket("/ws/{room_id}")
async def ws_room(websocket: WebSocket, room_id: str) -> None:
    username = websocket.query_params.get("username") or f"anon-{id(websocket):x}"
    user_id = int(websocket.query_params.get("user_id", "0"))
    elo = int(websocket.query_params.get("elo", "1200"))
    color = websocket.query_params.get("color", "white")

    await websocket.accept()

    room = ROOMS.get(room_id)
    if room is None:
        room = _create_room(room_id)
        ROOMS[room_id] = room

    room.connections[username] = websocket
    room.player_meta[username] = {"user_id": user_id, "elo": elo, "color": color}

    await state.redis.sadd(ROOMS_ACTIVE_SET, room_id)
    await state.redis.hset(_meta_key(room_id), mapping={f"{color}_player_id": user_id, f"{color}_elo": elo})
    await state.redis.set(_heartbeat_key(room_id), time.time())

    logger.info("Room %r: %r connected as %s (%d players now)", room_id, username, color, len(room.connections))
    await websocket.send_json({"type": "joined", "room_id": room_id, "color": color, "server_id": GAME_SERVER_ID})

    try:
        while True:
            message = await websocket.receive_json()
            if message.get("action") == "move":
                from_cell = Cell(message["from"]["row"], message["from"]["col"])
                to_cell = Cell(message["to"]["row"], message["to"]["col"])
                legality = room.arbiter.submit_move(from_cell, to_cell)
                await websocket.send_json({"type": "move_ack", "legality": legality.name})
            else:
                await websocket.send_json({"type": "error", "message": f"unknown action {message.get('action')!r}"})
    except WebSocketDisconnect:
        logger.info("Room %r: %r disconnected", room_id, username)
    finally:
        room.connections.pop(username, None)
        room.player_meta.pop(username, None)
        if not room.connections and not room.ended:
            ROOMS.pop(room_id, None)
