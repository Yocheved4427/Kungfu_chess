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
from shared.models.color import Color
from core.models import MoveCheckpoint, PendingJump, PendingMove
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


PAUSE_TTL_S = int(os.environ.get("PAUSE_TTL_S", str(24 * 60 * 60)))  # requirement 1: 24 hours


def _paused_key(room_id: str) -> str:
    return f"room:{room_id}:paused"


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
    paused: bool = False


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
    while room.connections and not room.state.game_over and not room.paused:
        await asyncio.sleep(TICK_INTERVAL_S)
        if not room.connections or room.paused:
            break
        room.arbiter.advance(int(TICK_INTERVAL_S * 1000))


async def _broadcast_loop(room: RoomGame) -> None:
    while room.connections and not room.paused:
        await asyncio.sleep(BROADCAST_INTERVAL_S)
        if not room.connections or room.paused:
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
# Pause & Resume
# ---------------------------------------------------------------------------
# Serializes the full GameState needed to resume correctly -- not just
# the board matrix and cooldowns named in the spec, but also in-flight
# moves (`pending`) and jumps (`airborne`). Omitting those would silently
# drop a move that was mid-flight the instant the game was paused: it
# would simply never arrive on resume, a real correctness bug, not a
# cosmetic one -- the piece would sit frozen at its origin forever.
#
# Cell/PendingMove/PendingJump/MoveCheckpoint are plain (frozen)
# dataclasses with no built-in JSON support, so each gets a small
# to-dict/from-dict pair below rather than a generic serializer -- the
# same "explicit over clever" preference the rest of this codebase
# already follows (see e.g. GameEvent.to_dict()).
# ---------------------------------------------------------------------------

def _cell_to_dict(cell: Cell) -> dict:
    return {"row": cell.row, "col": cell.col}


def _cell_from_dict(d: dict) -> Cell:
    return Cell(d["row"], d["col"])


def _checkpoint_to_dict(cp: MoveCheckpoint) -> dict:
    return {"pos": _cell_to_dict(cp.pos), "due_time": cp.due_time}


def _checkpoint_from_dict(d: dict) -> MoveCheckpoint:
    return MoveCheckpoint(pos=_cell_from_dict(d["pos"]), due_time=d["due_time"])


def _pending_move_to_dict(pm: PendingMove) -> dict:
    return {
        "piece": pm.piece,
        "from_pos": _cell_to_dict(pm.from_pos),
        "to_pos": _cell_to_dict(pm.to_pos),
        "arrival_time": pm.arrival_time,
        "start_time": pm.start_time,
        "checkpoints": [_checkpoint_to_dict(cp) for cp in pm.checkpoints],
        "next_checkpoint": pm.next_checkpoint,
    }


def _pending_move_from_dict(d: dict) -> PendingMove:
    return PendingMove(
        piece=d["piece"],
        from_pos=_cell_from_dict(d["from_pos"]),
        to_pos=_cell_from_dict(d["to_pos"]),
        arrival_time=d["arrival_time"],
        start_time=d["start_time"],
        checkpoints=tuple(_checkpoint_from_dict(cp) for cp in d["checkpoints"]),
        next_checkpoint=d["next_checkpoint"],
    )


def _pending_jump_to_dict(pj: PendingJump) -> dict:
    return {"piece": pj.piece, "pos": _cell_to_dict(pj.pos), "land_time": pj.land_time}


def _pending_jump_from_dict(d: dict) -> PendingJump:
    return PendingJump(piece=d["piece"], pos=_cell_from_dict(d["pos"]), land_time=d["land_time"])


def _serialize_room(room: RoomGame) -> dict:
    """requirement 1: board matrix, piece cooldowns, timer states (+
    everything else needed for a byte-for-byte-equivalent resume)."""
    state_ = room.state
    return {
        "board_rows": room.board.get_rows(),
        "current_time": state_.current_time,
        "pending": [_pending_move_to_dict(pm) for pm in state_.pending],
        "airborne": [_pending_jump_to_dict(pj) for pj in state_.airborne],
        "cooldowns": [
            {"row": cell.row, "col": cell.col, "expiry": expiry}
            for cell, expiry in state_.cooldowns.items()
        ],
        "game_over": state_.game_over,
        "winner": state_.winner.value if state_.winner is not None else None,
        "players": dict(room.player_meta),
        "paused_at": time.time(),
    }


def _restore_room(room_id: str, payload: dict) -> RoomGame:
    """requirement 3 (server side): reconstructs a room's GameEngine/
    GameState/RealTimeArbiter from a serialized snapshot -- the same
    shape _create_room builds, just seeded from Redis instead of
    ui.game_factory.STANDARD_BOARD_ROWS. Priming a fresh GameEngine's
    KingCaptureRule from THIS (mid-game, not starting) board is safe
    specifically because a room can only ever be paused while still in
    progress (_handle_pause refuses to pause an already-game_over room),
    so both kings are still necessarily on the board.
    """
    board = TextBoard(payload["board_rows"])
    game_state = GameState(
        board=board,
        current_time=payload["current_time"],
        pending=[_pending_move_from_dict(d) for d in payload["pending"]],
        airborne=[_pending_jump_from_dict(d) for d in payload["airborne"]],
        cooldowns={_cell_from_dict(c): c["expiry"] for c in payload["cooldowns"]},
        game_over=payload["game_over"],
        winner=Color(payload["winner"]) if payload["winner"] is not None else None,
    )
    engine = GameEngine(board)
    arbiter = RealTimeArbiter(engine, game_state)
    room = RoomGame(room_id=room_id, board=board, state=game_state, engine=engine, arbiter=arbiter)
    room.player_meta = {username: dict(meta) for username, meta in payload["players"].items()}
    arbiter.add_observer(_RoomObserver(room))
    asyncio.create_task(_tick_loop(room))
    asyncio.create_task(_broadcast_loop(room))
    return room


async def _handle_pause(room: RoomGame) -> None:
    """requirements 1 + 2: persist to Redis (24h TTL) then safely clear
    the room from local RAM, freeing this container's claimed capacity
    the same way a natural game-over does -- MINUS the Kafka
    game_ended publish, since a pause is not a game ending."""
    if room.paused or room.ended:
        return
    if room.state.game_over:
        # Nothing to pause -- the game already reached a real ending;
        # let the normal _handle_game_over path (already run, or about
        # to) own this room instead.
        return
    room.paused = True

    payload = _serialize_room(room)
    await state.redis.set(_paused_key(room.room_id), json.dumps(payload), ex=PAUSE_TTL_S)
    logger.info("Room %r paused and persisted to Redis (ttl=%ds)", room.room_id, PAUSE_TTL_S)

    for username, ws in list(room.connections.items()):
        try:
            await ws.send_json({"type": "paused", "room_id": room.room_id})
            await ws.close()
        except Exception:  # noqa: BLE001 -- best-effort notify; the room is pausing regardless
            logger.debug("Could not notify %r of pause (already disconnected?)", username)

    # Free this server's claimed capacity + live-room bookkeeping --
    # same keys _handle_game_over releases, so the Allocator's next
    # /allocate call can place a NEW room here, and the Reaper never
    # sees this room_id in rooms:active and mistakes it for abandoned.
    await state.redis.decr(f"gs:{GAME_SERVER_ID}:room_count")
    await state.redis.delete(f"room:{room.room_id}:game_server")
    await state.redis.srem(ROOMS_ACTIVE_SET, room.room_id)
    await state.redis.delete(_heartbeat_key(room.room_id))
    await state.redis.delete(_meta_key(room.room_id))

    room.connections.clear()
    room.player_meta.clear()
    ROOMS.pop(room.room_id, None)


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
        # requirement 3 (server side): a paused snapshot takes priority
        # over creating a fresh board -- this IS the "reload state from
        # Redis into the new server's RAM" step; it works identically
        # whether this happens to be the same container the room was
        # paused on or a brand new one the Allocator just assigned,
        # since nothing here depends on any local in-process state.
        paused_raw = await state.redis.get(_paused_key(room_id))
        if paused_raw is not None:
            # Deleted BEFORE restoring (single-use: resumed, not
            # replayable), deliberately -- NOT after. _restore_room
            # schedules the tick/broadcast loop tasks via
            # asyncio.create_task, and they start checking
            # `room.connections` (still empty at this point) the
            # instant this coroutine next hits an `await` -- an `await
            # state.redis.delete(...)` placed AFTER _restore_room, like
            # _create_room's own call site has NO await before it,
            # would hand control to the freshly-scheduled loops before
            # `room.connections[username] = websocket` below ever runs,
            # and both would see an empty connections dict and exit
            # immediately. Verified live: this exact ordering bug shipped
            # in the first version of this code path -- the room resumed
            # in Redis-log terms but never actually ticked.
            await state.redis.delete(_paused_key(room_id))
            room = _restore_room(room_id, json.loads(paused_raw))
            logger.info("Room %r resumed from paused Redis state (server=%r)", room_id, GAME_SERVER_ID)
        else:
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
            elif message.get("action") == "pause":
                # Either player may pause unilaterally -- "explicitly
                # leaves with the option to return later" (spec) is a
                # whole-room action, not a per-player one, same as this
                # engine has no turn structure to pause "your side" of.
                await _handle_pause(room)
                return  # _handle_pause already closed every connection, this one included
            else:
                await websocket.send_json({"type": "error", "message": f"unknown action {message.get('action')!r}"})
    except WebSocketDisconnect:
        logger.info("Room %r: %r disconnected", room_id, username)
    finally:
        room.connections.pop(username, None)
        room.player_meta.pop(username, None)
        if not room.connections and not room.ended:
            ROOMS.pop(room_id, None)
