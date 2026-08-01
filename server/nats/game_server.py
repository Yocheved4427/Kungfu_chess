from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import nats
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
# ---------------------------------------------------------------------------

DEFAULT_NATS_URL = "nats://localhost:4222"
EVENTS_WILDCARD_SUBJECT = "game.room.*.events"  # single wildcard token -- matches any room_id
MAX_PLAYERS = 2
TICK_INTERVAL_S = 0.03      # 30ms simulation tick, unchanged from every other real-time loop in this repo
BROADCAST_INTERVAL_S = 0.1  # 10Hz state broadcast (Server_Design.md decision 4)


def events_subject(room_id: str) -> str:
    return f"game.room.{room_id}.events"


def state_subject(room_id: str) -> str:
    return f"game.room.{room_id}.state"


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

    def __init__(self, nats_url: str = DEFAULT_NATS_URL) -> None:
        self._nats_url = nats_url
        self._nc: Optional[NatsClient] = None
        self._rooms: Dict[str, _RoomGame] = {}

    async def start(self) -> None:
        self._nc = await nats.connect(self._nats_url)
        await self._nc.subscribe(EVENTS_WILDCARD_SUBJECT, cb=self._on_event_message)
        logger.info(
            "NATS game server connected to %s, subscribed to %s",
            self._nats_url, EVENTS_WILDCARD_SUBJECT,
        )

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.drain()

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
            snapshot = {
                "type": "snapshot",
                "current_time": room.state.current_time,
                "board": room.board.get_rows(),
                "game_over": room.state.game_over,
                "winner": room.state.winner.value if room.state.winner is not None else None,
                "events": room.pending_events,
            }
            room.pending_events = []
            await self._publish_state(room.room_id, snapshot)

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
    args = parser.parse_args()

    setup_logging()
    server = NatsGameServer(args.nats_url)
    await server.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
