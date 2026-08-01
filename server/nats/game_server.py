from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import nats
import redis.asyncio as redis
from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg

from shared.logger_config import setup_logging
from shared.models.board import AbstractBoard, TextBoard
from shared.models.cell import Cell
from shared.models.color import Color
from engine.game import GameEngine
from engine.game_state import GameState
from server.game.real_time_arbiter import RealTimeArbiter
from ui.events import GameEvent, GameOverEvent, Observer
from ui.game_factory import STANDARD_BOARD_ROWS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kung Fu Chess -- NATS-based Game Server (server/nats/game_server.py)
# ---------------------------------------------------------------------------
# Replaces server/network/server.py's raw-TCP transport with NATS Core
# pub/sub, room-scoped by SUBJECT (`game.room.<room_id>.events` /
# `game.room.<room_id>.state`) instead of by a socket connection. Reuses
# rather than reimplements the actual game logic: one authoritative
# RealTimeArbiter/GameEngine/GameState per room, exactly as
# server/network/server.py's own NetworkServer._start_game builds one --
# NATS only changes how moves reach this server and how state reaches
# clients.
#
# RoomService (server/services/room_service.py) is deliberately NOT
# reused here: it generates its own random room_id on create_room(),
# but NATS's subject-embedded room_id must be chosen by whoever
# publishes the first "join" for that room -- the two id-ownership
# models don't fit together, and forcing them to would be more
# convoluted than the few lines of inline membership tracking below
# (_RoomGame.players). RealTimeArbiter/GameEngine -- the parts that
# would actually be risky or wasteful to duplicate -- are reused
# unchanged.
#
# Room/opponent PAIRING (which two players end up sharing a room_id) is
# considered upstream of this module, same as it would be for a real
# deployment pairing this with server/services/matchmaking_service.py --
# this server has no opinion on how a room_id was chosen, only on what
# happens once two players have joined one.
#
# Spectator support: alongside its own NATS state broadcast, this server
# ALSO publishes a lightweight cell-diff to Redis Pub/Sub whenever a
# room's board actually changes -- for server/spectator/gateway.py to
# consume. This is a SECOND, independent pub/sub channel for a SECOND,
# independent audience (spectators, potentially thousands per room, vs.
# exactly 2 players over NATS) -- not a replacement for the NATS state
# broadcast, and this server has zero knowledge of how many spectators
# exist or how they connect (that's the Gateway's job entirely, see its
# own module docstring). Redis was chosen over a second NATS subject
# specifically because the Gateway needs to buffer/delay each message
# (decision 3 in the spectator spec) rather than just relay it, which is
# a Gateway-side concern either way -- reusing the SAME broadcast loop
# that already runs at 10Hz (Server_Design.md decision 4) rather than
# adding a second one, since "the board changed" is already known there.
# ---------------------------------------------------------------------------

DEFAULT_NATS_URL = "nats://localhost:4222"
DEFAULT_REDIS_HOST = "localhost"
DEFAULT_REDIS_PORT = 6379
EVENTS_WILDCARD_SUBJECT = "game.room.*.events"  # single wildcard token -- matches any room_id
MAX_PLAYERS = 2
TICK_INTERVAL_S = 0.03      # 30ms simulation tick, unchanged from every other real-time loop in this repo
BROADCAST_INTERVAL_S = 0.1  # 10Hz state broadcast (Server_Design.md decision 4)


def events_subject(room_id: str) -> str:
    return f"game.room.{room_id}.events"


def state_subject(room_id: str) -> str:
    return f"game.room.{room_id}.state"


def diff_channel(room_id: str) -> str:
    """Redis Pub/Sub channel server/spectator/gateway.py subscribes to
    (via a `game.room.*.diff` pattern subscription) -- deliberately the
    same `game.room.<room_id>.*` shape as the NATS subjects above, even
    though it's a different broker, so the room-addressing scheme reads
    as one consistent convention across both transports."""
    return f"game.room.{room_id}.diff"


@dataclass
class _RoomGame:
    room_id: str
    board: AbstractBoard
    state: GameState
    engine: GameEngine
    arbiter: RealTimeArbiter
    players: List[str] = field(default_factory=list)   # join order -> players[0]=White, players[1]=Black
    colors: Dict[str, Color] = field(default_factory=dict)
    pending_events: list = field(default_factory=list)
    tick_task: Optional[asyncio.Task] = None
    broadcast_task: Optional[asyncio.Task] = None
    ended: bool = False
    last_broadcast_rows: Optional[List[str]] = None  # for spectator cell-diffing, see _diff_cells


class _RoomObserver(Observer):
    """Bridges GameEngine's synchronous Observer callback into this
    room's event buffer (flushed at the 10Hz broadcast cadence), and
    schedules the game-over cleanup immediately rather than waiting for
    the next broadcast tick."""

    def __init__(self, server: "NatsGameServer", room: _RoomGame) -> None:
        self._server = server
        self._room = room

    def on_event(self, event: GameEvent) -> None:
        self._room.pending_events.append(event.to_dict())
        if isinstance(event, GameOverEvent):
            asyncio.create_task(self._server._handle_game_over(self._room))


class NatsGameServer:
    """Authoritative, room-scoped Kung Fu Chess server over NATS Core.

    One `GameEngine`/`GameState`/`RealTimeArbiter` per room, held in
    memory (`self._rooms`) for as long as that room's game runs --
    "validates the logic and cooldowns in RAM", per spec.
    """

    def __init__(
        self,
        nats_url: str = DEFAULT_NATS_URL,
        redis_host: str = DEFAULT_REDIS_HOST,
        redis_port: int = DEFAULT_REDIS_PORT,
    ) -> None:
        self._nats_url = nats_url
        self._redis_host = redis_host
        self._redis_port = redis_port
        self._nc: Optional[NatsClient] = None
        self._redis: Optional[redis.Redis] = None
        self._rooms: Dict[str, _RoomGame] = {}

    async def start(self) -> None:
        self._nc = await nats.connect(self._nats_url)
        await self._nc.subscribe(EVENTS_WILDCARD_SUBJECT, cb=self._on_event_message)
        logger.info(
            "NATS game server connected to %s, subscribed to %s",
            self._nats_url, EVENTS_WILDCARD_SUBJECT,
        )

        self._redis = redis.Redis(host=self._redis_host, port=self._redis_port)
        await self._redis.ping()
        logger.info("Connected to Redis at %s:%d for spectator diffs", self._redis_host, self._redis_port)

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.drain()
        if self._redis is not None:
            await self._redis.aclose()

    async def run_forever(self) -> None:
        await self.start()
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await self.close()

    # ------------------------------------------------------------------
    # Inbound: game.room.*.events
    # ------------------------------------------------------------------

    async def _on_event_message(self, msg: Msg) -> None:
        # "game.room.<room_id>.events" -- index 2 is the wildcard token
        # the subscription's "*" actually matched.
        room_id = msg.subject.split(".")[2]
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            logger.warning("Malformed event on %s: %r", msg.subject, msg.data)
            return

        action = payload.get("type")
        if action == "join":
            await self._handle_join(room_id, payload)
        elif action == "move":
            await self._handle_move(room_id, payload)
        else:
            await self._publish_state(room_id, {"type": "error", "message": f"unknown action {action!r}"})

    async def _handle_join(self, room_id: str, payload: dict) -> None:
        username = payload.get("player")
        if not username:
            await self._publish_state(room_id, {"type": "error", "message": "join requires 'player'"})
            return

        room = self._rooms.get(room_id)
        if room is None:
            room = self._create_room(room_id)
            self._rooms[room_id] = room

        if username in room.players:
            await self._publish_state(room_id, {"type": "error", "message": f"{username!r} already joined"})
            return
        if len(room.players) >= MAX_PLAYERS:
            await self._publish_state(room_id, {"type": "error", "message": "room is full"})
            return

        color = Color.WHITE if not room.players else Color.BLACK
        room.players.append(username)
        room.colors[username] = color
        logger.info("Room %r: %r joined as %s (%d/%d)", room_id, username, color.name, len(room.players), MAX_PLAYERS)
        await self._publish_state(room_id, {"type": "joined", "player": username, "color": color.value})

        if len(room.players) == MAX_PLAYERS:
            room.tick_task = asyncio.create_task(self._tick_loop(room))
            room.broadcast_task = asyncio.create_task(self._broadcast_loop(room))

    async def _handle_move(self, room_id: str, payload: dict) -> None:
        room = self._rooms.get(room_id)
        if room is None or len(room.players) < MAX_PLAYERS:
            await self._publish_state(room_id, {"type": "error", "message": "room not started (need 2 players)"})
            return

        username = payload.get("player")
        color = room.colors.get(username)
        try:
            from_cell = Cell(payload["from"]["row"], payload["from"]["col"])
            to_cell = Cell(payload["to"]["row"], payload["to"]["col"])
        except (KeyError, TypeError):
            await self._publish_state(room_id, {"type": "error", "message": "malformed move payload"})
            return

        # Real-time gameplay has no turn order, but a player must still
        # only ever move their OWN colour's pieces -- same guard as
        # server/network/server.py's own _handle_move_piece.
        piece = room.state.board.get_piece_at(from_cell)
        if piece is None or piece == "." or color is None or piece[0] != color.value:
            await self._publish_state(
                room_id,
                {"type": "error", "message": f"{username!r} does not control the piece at {from_cell!r}"},
            )
            return

        legality = room.arbiter.submit_move(from_cell, to_cell)
        await self._publish_state(room_id, {"type": "move_ack", "player": username, "legality": legality.name})

    # ------------------------------------------------------------------
    # Room lifecycle
    # ------------------------------------------------------------------

    def _create_room(self, room_id: str) -> _RoomGame:
        board = TextBoard(STANDARD_BOARD_ROWS)
        state = GameState(board=board)
        engine = GameEngine(board)
        arbiter = RealTimeArbiter(engine, state)
        room = _RoomGame(room_id=room_id, board=board, state=state, engine=engine, arbiter=arbiter)
        arbiter.add_observer(_RoomObserver(self, room))
        return room

    async def _tick_loop(self, room: _RoomGame) -> None:
        while not room.state.game_over:
            await asyncio.sleep(TICK_INTERVAL_S)
            if room.state.game_over:
                break
            room.arbiter.advance(int(TICK_INTERVAL_S * 1000))

    async def _broadcast_loop(self, room: _RoomGame) -> None:
        while not room.ended:
            await asyncio.sleep(BROADCAST_INTERVAL_S)
            current_rows = room.board.get_rows()
            snapshot = {
                "type": "snapshot",
                "current_time": room.state.current_time,
                "board": current_rows,
                "game_over": room.state.game_over,
                "winner": room.state.winner.value if room.state.winner is not None else None,
                "events": room.pending_events,
            }
            room.pending_events = []
            await self._publish_state(room.room_id, snapshot)
            await self._publish_diff_if_changed(room, current_rows)

    async def _publish_diff_if_changed(self, room: _RoomGame, current_rows: List[str]) -> None:
        """Publish a lightweight {row, col, piece} cell-diff to Redis for
        server/spectator/gateway.py, but only when something actually
        moved since the last broadcast -- "whenever a valid move occurs",
        per spec, rather than an empty diff every 100ms while a room is
        idle between moves.

        Computed by comparing full board rows rather than inferring a
        diff from the MoveCompletedEvent that triggered it, deliberately:
        a bare "piece moved from A to B" doesn't capture what happened at
        the destination cell (a capture) or a landing-square promotion
        (engine.game.GameEngine._maybe_promote silently rewrites the
        board without its own event) -- comparing the actual before/after
        cell contents is correct regardless of *why* a cell changed.
        """
        changed_cells = self._diff_cells(room.last_broadcast_rows, current_rows)
        room.last_broadcast_rows = current_rows
        if not changed_cells:
            return

        payload = {
            "type": "diff",
            "room_id": room.room_id,
            "changed_cells": changed_cells,
            "current_time": room.state.current_time,
            "game_over": room.state.game_over,
            "winner": room.state.winner.value if room.state.winner is not None else None,
        }
        await self._redis.publish(diff_channel(room.room_id), json.dumps(payload))

    @staticmethod
    def _diff_cells(previous_rows: Optional[List[str]], current_rows: List[str]) -> List[dict]:
        """Every (row, col) whose token differs between *previous_rows*
        and *current_rows*, as ``{"row": r, "col": c, "piece": token}``.
        ``previous_rows`` is ``None`` on a room's very first broadcast --
        every occupied cell counts as "changed" then, since a spectator
        gateway has nothing to diff against yet either (it starts every
        room from the same standard layout -- see
        server/spectator/gateway.py's `_SpectatorRoom.public_board`)."""
        changed: List[dict] = []
        for row_index, new_row in enumerate(current_rows):
            old_row = previous_rows[row_index] if previous_rows is not None else None
            old_tokens = old_row.split() if old_row is not None else []
            new_tokens = new_row.split()
            for col_index, new_token in enumerate(new_tokens):
                old_token = old_tokens[col_index] if col_index < len(old_tokens) else None
                if new_token != old_token:
                    changed.append({"row": row_index, "col": col_index, "piece": new_token})
        return changed

    async def _handle_game_over(self, room: _RoomGame) -> None:
        if room.ended:
            return
        room.ended = True
        logger.info("Room %r game over: winner=%s", room.room_id, room.state.winner)
        # The room stays in self._rooms so a client subscribing late
        # still receives the final snapshot from _broadcast_loop's last
        # pass; both tasks exit on their own next wake (tick_loop's own
        # `while not room.state.game_over`, broadcast_loop's `while not
        # room.ended`) -- no explicit cancellation needed. A real
        # deployment would evict finished rooms after a grace period;
        # out of scope for this transport-focused module.

    async def _publish_state(self, room_id: str, payload: dict) -> None:
        await self._nc.publish(state_subject(room_id), json.dumps(payload).encode("utf-8"))


async def main() -> None:
    parser = argparse.ArgumentParser(description="Kung Fu Chess NATS game server")
    parser.add_argument("--nats-url", default=DEFAULT_NATS_URL, help=f"Default: {DEFAULT_NATS_URL}")
    parser.add_argument("--redis-host", default=DEFAULT_REDIS_HOST, help=f"Default: {DEFAULT_REDIS_HOST}")
    parser.add_argument("--redis-port", type=int, default=DEFAULT_REDIS_PORT, help=f"Default: {DEFAULT_REDIS_PORT}")
    args = parser.parse_args()

    setup_logging()
    server = NatsGameServer(args.nats_url, args.redis_host, args.redis_port)
    await server.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
