from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from typing import List, Optional

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from core.models import Color
from engine.board import TextBoard
from engine.game import GameEngine
from engine.game_state import GameState
from logger_config import setup_logging
from server.algebraic import AlgebraicNotationError, algebraic_to_position
from ui.events import GameEvent, Observer
from ui.game_factory import STANDARD_BOARD_ROWS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kung Fu Chess – WebSocket Server
# ---------------------------------------------------------------------------
# Single-process, two-player, no login/matchmaking/rooms (all later
# tasks) — this is pure "does the real-time pipeline work over a
# network" preparation. One shared GameEngine + GameState, exactly the
# same objects ui/game_factory.py's _new_game() builds for the GUI, just
# driven by parsed algebraic-notation moves from two WebSocket clients
# instead of mouse clicks.
#
# server/ imports from engine/, core/, and ui/ (ui.events for the Bus
# contract + serialization, ui.game_factory for STANDARD_BOARD_ROWS) —
# never the reverse; nothing in engine/, core/, or ui/ imports anything
# from server/.
#
# Wire protocol (JSON, one message per WebSocket text frame):
#
#   Client -> server:
#     {"type": "move", "from": "e2", "to": "e4"}
#
#   Server -> client, on connect (once):
#     {"type": "assigned_color", "color": "w"}          -- or "b"
#     {"type": "error", "message": "..."}               -- if already full,
#                                                            connection is
#                                                            closed right after
#
#   Server -> client, ongoing:
#     {"type": "error", "message": "..."}                -- reply to a bad
#                                                             command, sent
#                                                             only to the
#                                                             client that sent it
#     {"type": "<GameEvent subclass name>", ...}          -- every event
#                                                             GameEngine fires,
#                                                             serialized via
#                                                             GameEvent.to_dict()
#                                                             (see ui/events.py),
#                                                             broadcast to both
#                                                             clients
#     {"type": "snapshot", "board": [...], "current_time": int,
#      "game_over": bool, "winner": "w"|"b"|null}         -- full-board resync,
#                                                             broadcast once per
#                                                             tick (see
#                                                             GameServer._tick_loop)
# ---------------------------------------------------------------------------

TICK_INTERVAL_S = 0.03  # 30ms -- matches main_gui.py's own render-loop cadence
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765


class _BroadcastObserver(Observer):
    """Bridges GameEngine's synchronous Observer callback to the async
    world: every event it receives is serialized and pushed onto an
    ``asyncio.Queue`` — ``put_nowait`` is safe to call from sync code as
    long as we're on the event loop's thread (true here: ``on_event``
    only ever fires from inside ``GameEngine.tick``/``attempt_move``,
    both called from this module's own async handlers). A separate
    coroutine (``GameServer._broadcast_loop``) drains the queue and does
    the actual ``await websocket.send(...)`` calls.
    """

    def __init__(self, queue: "asyncio.Queue[dict]") -> None:
        self._queue = queue

    def on_event(self, event: GameEvent) -> None:
        self._queue.put_nowait(event.to_dict())


class GameServer:
    """Owns the one shared game in progress and every connected client.

    Exactly two players: the first connection to arrive takes an empty
    White/Black slot (in that order), the next takes the other, and any
    further connection is rejected outright (see ``handler``). Slots
    free up on disconnect so a later connection can take a vacated one
    — there's no real matchmaking/reconnection identity yet (later
    task), just "don't permanently wedge a slot shut".
    """

    def __init__(self) -> None:
        self.board = TextBoard(STANDARD_BOARD_ROWS)
        self.state = GameState(board=self.board)
        self.engine = GameEngine(self.board)

        self._broadcast_queue: "asyncio.Queue[dict]" = asyncio.Queue()
        self.engine.add_observer(_BroadcastObserver(self._broadcast_queue))

        self._white: Optional[ServerConnection] = None
        self._black: Optional[ServerConnection] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def _assign_color(self, websocket: ServerConnection) -> Optional[Color]:
        """Claim a free colour slot for *websocket*, or None if both are taken."""
        if self._white is None:
            self._white = websocket
            return Color.WHITE
        if self._black is None:
            self._black = websocket
            return Color.BLACK
        return None

    def _release_color(self, websocket: ServerConnection) -> None:
        """Free whichever slot *websocket* held, if any."""
        if self._white is websocket:
            self._white = None
        elif self._black is websocket:
            self._black = None

    def _connections(self) -> List[ServerConnection]:
        return [ws for ws in (self._white, self._black) if ws is not None]

    async def handler(self, websocket: ServerConnection) -> None:
        """Per-connection entry point registered with ``websockets.serve``.

        Assigns a colour or rejects the connection outright if both
        slots are already taken, then reads move commands from this
        client until it disconnects.
        """
        color = self._assign_color(websocket)
        if color is None:
            await self._send(websocket, {
                "type": "error",
                "message": "Server already has two players connected.",
            })
            await websocket.close()
            return

        logger.info("Player connected as %s", color.value)
        await self._send(websocket, {"type": "assigned_color", "color": color.value})

        try:
            async for raw in websocket:
                await self._handle_message(websocket, color, raw)
        except ConnectionClosed:
            pass
        finally:
            self._release_color(websocket)
            logger.info("Player disconnected (%s)", color.value)

    # ------------------------------------------------------------------
    # Incoming messages
    # ------------------------------------------------------------------

    async def _handle_message(self, websocket: ServerConnection, color: Color, raw: str) -> None:
        """Parse and dispatch one incoming client message.

        Never raises — any malformed/illegal command is reported back
        to *websocket* alone via an ``error`` message, per the wire
        protocol (see this module's own header); the connection and the
        rest of the server are unaffected either way.
        """
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            await self._send_error(websocket, "Malformed JSON")
            return

        if not isinstance(message, dict):
            await self._send_error(websocket, "Message must be a JSON object")
            return

        if message.get("type") != "move":
            await self._send_error(websocket, f"Unknown message type: {message.get('type')!r}")
            return

        await self._handle_move(websocket, color, message)

    async def _handle_move(self, websocket: ServerConnection, color: Color, message: dict) -> None:
        from_square = message.get("from")
        to_square = message.get("to")
        try:
            from_pos = algebraic_to_position(from_square)
            to_pos = algebraic_to_position(to_square)
        except AlgebraicNotationError as e:
            await self._send_error(websocket, str(e))
            return

        # Real-time gameplay has no turn order (either side may move
        # anytime — see GameEngine.attempt_move's own docstring), but a
        # connection must still only ever move ITS OWN colour's pieces.
        # GameEngine enforces no such thing itself (attempt_move only
        # checks shape/path/busy-state), so the server must — same
        # guard ui/game_loop.py's _OwnColorClickController already
        # applies for the two-player GUI's split-screen input.
        piece = self.state.board.get_piece_at(from_pos)
        if piece is None or piece == "." or piece[0] != color.value:
            await self._send_error(websocket, f"You do not control the piece at {from_square!r}")
            return

        if not self.engine.attempt_move(self.state, from_pos, to_pos):
            await self._send_error(websocket, f"Illegal move: {from_square} to {to_square}")

    # ------------------------------------------------------------------
    # Outgoing messages
    # ------------------------------------------------------------------

    async def _send(self, websocket: ServerConnection, payload: dict) -> None:
        try:
            await websocket.send(json.dumps(payload))
        except ConnectionClosed:
            pass  # the client is gone; nothing further to do

    async def _send_error(self, websocket: ServerConnection, message: str) -> None:
        await self._send(websocket, {"type": "error", "message": message})

    async def _broadcast(self, payload: dict) -> None:
        data = json.dumps(payload)
        for websocket in self._connections():
            try:
                await websocket.send(data)
            except ConnectionClosed:
                pass  # that client is gone; the other still gets it

    async def _broadcast_snapshot(self) -> None:
        """A full-board resync, independent of the per-event broadcasts
        below — every tick, simplest option to start with (see this
        module's own header); a client can always rebuild its view from
        this alone even if it missed individual events."""
        await self._broadcast({
            "type": "snapshot",
            "board": self.board.get_rows(),
            "current_time": self.state.current_time,
            "game_over": self.state.game_over,
            "winner": self.state.winner.value if self.state.winner is not None else None,
        })

    # ------------------------------------------------------------------
    # Background loops
    # ------------------------------------------------------------------

    async def _tick_loop(self) -> None:
        """Advance the game clock on a fixed real-time interval,
        regardless of client activity — the same frame-rate-independent
        approach main_gui.py's render loop uses (real elapsed wall-clock
        time between iterations via time.time(), not a fixed per-tick
        constant), just paced by asyncio.sleep instead of cv2.waitKey.
        """
        last_time = time.time()
        while True:
            await asyncio.sleep(TICK_INTERVAL_S)
            now = time.time()
            elapsed_ms = int((now - last_time) * 1000)
            last_time = now

            self.engine.tick(self.state, elapsed_ms)
            await self._broadcast_snapshot()

    async def _broadcast_loop(self) -> None:
        """Drain events _BroadcastObserver queued and send each to both
        connected clients, in the order GameEngine fired them."""
        while True:
            payload = await self._broadcast_queue.get()
            await self._broadcast(payload)

    async def run_forever(self) -> None:
        """Run the tick loop and the broadcast-drain loop concurrently,
        forever — call once, after the WebSocket listener is up."""
        await asyncio.gather(self._tick_loop(), self._broadcast_loop())


async def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    server = GameServer()
    async with serve(server.handler, host, port):
        logger.info("Kung Fu Chess server listening on ws://%s:%d", host, port)
        await server.run_forever()


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Kung Fu Chess WebSocket server")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    try:
        asyncio.run(run_server(args.host, args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
