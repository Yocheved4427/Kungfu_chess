from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Dict, Optional

import redis.asyncio as redis
from aiokafka import AIOKafkaProducer

from shared.models.board import TextBoard
from shared.models.cell import Cell
from shared.models.color import Color
from engine.game import GameEngine
from engine.game_state import GameState
from server.game.real_time_arbiter import RealTimeArbiter
from server.game.rules.rule_engine import MoveLegality
from ui.events import GameEvent, GameOverEvent, Observer
from ui.game_factory import STANDARD_BOARD_ROWS

from services.game_server.domain import (
    Connection,
    PlayerMeta,
    RoomError,
    RoomGame,
    RoomNotActiveError,
    RoomStatus,
    elo_deltas,
)
from services.game_server.serialization import (
    game_state_from_dict,
    game_state_to_dict,
    player_meta_from_dict,
    player_meta_to_dict,
)

logger = logging.getLogger("game_server")

# ---------------------------------------------------------------------------
# Kung Fu Chess -- Game Server business logic (services/game_server/room_service.py)
# ---------------------------------------------------------------------------
# The "Model"/service layer: owns room lifecycle (create/restore/join/
# leave/pause/game-over) and the persistence side effects each of those
# implies. Every dependency (Redis, Kafka) is constructor-injected, not
# reached through a module-level global -- this class can be constructed
# with fakes in a test with no FastAPI, no real network, nothing running.
#
# Every public method either succeeds or raises a RoomError subclass
# (domain.py) -- see that module's own docstring for why. The one
# FastAPI-facing module, main.py, is the only place that catches these
# and turns them into WebSocket error messages; this class itself never
# imports fastapi.
# ---------------------------------------------------------------------------

TICK_INTERVAL_S = 0.03      # 30ms simulation tick (unchanged from RealTimeArbiter's own cadence)
BROADCAST_INTERVAL_S = 0.1  # 10Hz state broadcast (Server_Design.md decision 4)

GAME_SERVERS_SET = "gs:all"
ROOMS_ACTIVE_SET = "rooms:active"


def _heartbeat_key(room_id: str) -> str:
    return f"room:{room_id}:heartbeat"


def _meta_key(room_id: str) -> str:
    return f"room:{room_id}:meta"


def _paused_key(room_id: str) -> str:
    return f"room:{room_id}:paused"


def _game_server_key(room_id: str) -> str:
    return f"room:{room_id}:game_server"


class _RoomObserver(Observer):
    """Bridges GameEngine's synchronous Observer callback into this
    room's event buffer (flushed at the 10Hz broadcast cadence), and
    schedules the game-over handler immediately rather than waiting for
    the next broadcast tick."""

    def __init__(self, service: "RoomService", room: RoomGame) -> None:
        self._service = service
        self._room = room

    def on_event(self, event: GameEvent) -> None:
        self._room.pending_events.append(event.to_dict())
        if isinstance(event, GameOverEvent):
            asyncio.create_task(self._service._handle_game_over(self._room, event))


class RoomService:
    def __init__(
        self,
        redis_client: redis.Redis,
        kafka_producer: AIOKafkaProducer,
        game_server_id: str,
        game_ended_topic: str,
        pause_ttl_s: int,
    ) -> None:
        self._redis = redis_client
        self._kafka_producer = kafka_producer
        self._game_server_id = game_server_id
        self._game_ended_topic = game_ended_topic
        self._pause_ttl_s = pause_ttl_s
        self._rooms: Dict[str, RoomGame] = {}
        # Guards the check-then-create/restore race: two simultaneous
        # first connections to the same brand-new room_id could otherwise
        # each see "no room yet" and each build a separate RoomGame, the
        # second silently clobbering the first's connection registration.
        self._lock = asyncio.Lock()

    @property
    def rooms(self) -> Dict[str, RoomGame]:
        return self._rooms

    # ------------------------------------------------------------------
    # Join / leave
    # ------------------------------------------------------------------

    async def join_room(
        self, room_id: str, username: str, meta: PlayerMeta, connection: Connection
    ) -> RoomGame:
        async with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                room = await self._get_or_restore(room_id)
                self._rooms[room_id] = room

            if room.status is not RoomStatus.ACTIVE:
                raise RoomNotActiveError(room_id, room.status)

            is_first_connection = not room.connections
            room.connections[username] = connection
            room.players[username] = meta

            # Started here, gated on "did this connection just create the
            # room's first live connection" -- NOT on room creation
            # itself. An earlier version started these tasks unconditionally
            # inside room creation and relied on no `await` happening
            # before the caller registered the connection; a resume path
            # that added one `await` in between broke that silently (the
            # loops saw an empty connections dict on their first wake and
            # exited immediately -- verified live, in production use).
            # Gating on the lock-held, connection-already-registered state
            # removes that fragile ordering dependency entirely.
            if is_first_connection:
                asyncio.create_task(self._tick_loop(room))
                asyncio.create_task(self._broadcast_loop(room))

        await self._redis.sadd(ROOMS_ACTIVE_SET, room_id)
        await self._redis.hset(
            _meta_key(room_id),
            mapping={f"{meta.color.value}_player_id": meta.user_id, f"{meta.color.value}_elo": meta.elo},
        )
        await self._redis.set(_heartbeat_key(room_id), time.time())
        return room

    async def leave_room(self, room: RoomGame, username: str) -> None:
        room.connections.pop(username, None)
        room.players.pop(username, None)
        if not room.connections and room.status is not RoomStatus.ENDED:
            async with self._lock:
                self._rooms.pop(room.room_id, None)

    # ------------------------------------------------------------------
    # Moves
    # ------------------------------------------------------------------

    def submit_move(self, room: RoomGame, from_cell: Cell, to_cell: Cell) -> MoveLegality:
        if room.status is not RoomStatus.ACTIVE:
            raise RoomNotActiveError(room.room_id, room.status)
        return room.arbiter.submit_move(from_cell, to_cell)

    # ------------------------------------------------------------------
    # Room creation / restoration
    # ------------------------------------------------------------------

    async def _get_or_restore(self, room_id: str) -> RoomGame:
        """requirement 3 (server side): a paused snapshot takes priority
        over creating a fresh board -- this IS "reload state from Redis
        into the new server's RAM". Works identically whether this
        happens to be the same container the room was paused on or a
        brand new one the Allocator just assigned, since nothing here
        depends on any local in-process state.
        """
        raw = await self._redis.get(_paused_key(room_id))
        if raw is None:
            return self._create_room(room_id)

        await self._redis.delete(_paused_key(room_id))  # single-use: resumed, not replayable
        payload = json.loads(raw)
        board, game_state = game_state_from_dict(payload)
        engine = GameEngine(board)
        arbiter = RealTimeArbiter(engine, game_state)
        room = RoomGame(room_id=room_id, board=board, state=game_state, engine=engine, arbiter=arbiter)
        room.players = {u: player_meta_from_dict(d) for u, d in payload["players"].items()}
        arbiter.add_observer(_RoomObserver(self, room))
        logger.info("Room %r resumed from paused Redis state (server=%r)", room_id, self._game_server_id)
        return room

    def _create_room(self, room_id: str) -> RoomGame:
        board = TextBoard(STANDARD_BOARD_ROWS)
        game_state = GameState(board=board)
        engine = GameEngine(board)
        arbiter = RealTimeArbiter(engine, game_state)
        room = RoomGame(room_id=room_id, board=board, state=game_state, engine=engine, arbiter=arbiter)
        arbiter.add_observer(_RoomObserver(self, room))
        return room

    # ------------------------------------------------------------------
    # Tick / broadcast
    # ------------------------------------------------------------------

    async def _tick_loop(self, room: RoomGame) -> None:
        while room.connections and room.status is RoomStatus.ACTIVE:
            await asyncio.sleep(TICK_INTERVAL_S)
            if not room.connections or room.status is not RoomStatus.ACTIVE:
                break
            room.arbiter.advance(int(TICK_INTERVAL_S * 1000))

    async def _broadcast_loop(self, room: RoomGame) -> None:
        while room.connections and room.status is RoomStatus.ACTIVE:
            await asyncio.sleep(BROADCAST_INTERVAL_S)
            if not room.connections or room.status is not RoomStatus.ACTIVE:
                break
            # The heartbeat services/reaper/main.py polls for. Once both
            # players disconnect, the `while room.connections:` guard
            # above stops this loop (and thus this refresh) on its own --
            # a stale heartbeat IS the abandonment signal, by design; see
            # services/reaper/main.py's own module docstring.
            await self._redis.set(_heartbeat_key(room.room_id), time.time())

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
            for username, connection in room.connections.items():
                try:
                    await connection.send_json(snapshot)
                except Exception:  # noqa: BLE001 -- a broken connection is cleaned up below, not raised
                    dead.append(username)
            for username in dead:
                room.connections.pop(username, None)
                room.players.pop(username, None)

    # ------------------------------------------------------------------
    # Pause & Resume
    # ------------------------------------------------------------------

    async def pause_room(self, room: RoomGame) -> None:
        """requirements 1 + 2: persist to Redis (24h TTL) then safely
        clear the room from local RAM, freeing this container's claimed
        capacity the same way game-over does -- MINUS the Kafka
        game_ended publish, since a pause is not a game ending.

        Raises RoomNotActiveError (never a silent no-op) if the room is
        already paused or already ended -- a caller (main.py) can turn
        that into a clean "already paused" WS error instead of the
        client getting no feedback at all for a rejected double-pause.
        """
        if room.status is not RoomStatus.ACTIVE:
            raise RoomNotActiveError(room.room_id, room.status)
        room.status = RoomStatus.PAUSED

        payload = {
            **game_state_to_dict(room.board, room.state),
            "players": {u: player_meta_to_dict(m) for u, m in room.players.items()},
            "paused_at": time.time(),
        }
        await self._redis.set(_paused_key(room.room_id), json.dumps(payload), ex=self._pause_ttl_s)
        logger.info("Room %r paused and persisted to Redis (ttl=%ds)", room.room_id, self._pause_ttl_s)

        for username, connection in list(room.connections.items()):
            try:
                await connection.send_json({"type": "paused", "room_id": room.room_id})
                await connection.close()
            except Exception:  # noqa: BLE001 -- best-effort notify; the room is pausing regardless
                logger.debug("Could not notify %r of pause (already disconnected?)", username)

        # Free this server's claimed capacity + live-room bookkeeping in
        # one atomic round trip -- a crash between these five keys used
        # to be able to leave Allocator bookkeeping inconsistent (e.g.
        # capacity freed but the room:game_server pointer still claimed).
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.decr(f"gs:{self._game_server_id}:room_count")
            pipe.delete(_game_server_key(room.room_id))
            pipe.srem(ROOMS_ACTIVE_SET, room.room_id)
            pipe.delete(_heartbeat_key(room.room_id))
            pipe.delete(_meta_key(room.room_id))
            await pipe.execute()

        room.connections.clear()
        room.players.clear()
        async with self._lock:
            self._rooms.pop(room.room_id, None)

    # ------------------------------------------------------------------
    # Game over
    # ------------------------------------------------------------------

    async def _handle_game_over(self, room: RoomGame, event: GameOverEvent) -> None:
        # Not a Gatekeeper check (no external caller is waiting on this
        # method's result to react to) -- GameOverEvent is documented to
        # fire at most once per game (engine/game.py's own
        # _check_game_over), so this is a defensive idempotency guard
        # against that firing twice, not input validation.
        if room.status is not RoomStatus.ACTIVE:
            return
        room.status = RoomStatus.ENDED

        white = room.player_by_color(Color.WHITE)
        black = room.player_by_color(Color.BLACK)
        white_delta, black_delta = (
            elo_deltas(white.elo, black.elo, event.winner) if white and black else (0, 0)
        )
        winner_user_id = None
        if event.winner is Color.WHITE and white:
            winner_user_id = white.user_id
        elif event.winner is Color.BLACK and black:
            winner_user_id = black.user_id

        payload = {
            "game_id": room.room_id,
            "white_player_id": white.user_id if white else 0,
            "black_player_id": black.user_id if black else 0,
            "winner_id": winner_user_id,
            "white_elo_delta": white_delta,
            "black_elo_delta": black_delta,
            "moves": [],
            "ended_at": time.time(),
        }
        await self._kafka_producer.send_and_wait(self._game_ended_topic, json.dumps(payload).encode("utf-8"))
        logger.info("Published game_ended for room %r: %s", room.room_id, payload)

        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.decr(f"gs:{self._game_server_id}:room_count")
            pipe.delete(_game_server_key(room.room_id))
            pipe.srem(ROOMS_ACTIVE_SET, room.room_id)
            pipe.delete(_heartbeat_key(room.room_id))
            pipe.delete(_meta_key(room.room_id))
            await pipe.execute()
