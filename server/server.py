from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from typing import Dict, List, Optional

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from core.models import Color
from engine.game import GameEngine
from engine.game_state import GameState
from engine.board import TextBoard
from logger_config import setup_logging
from server.algebraic import AlgebraicNotationError, algebraic_to_position
from ui.events import GameEvent, Observer
from ui.game_factory import STANDARD_BOARD_ROWS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kung Fu Chess – WebSocket Server
# ---------------------------------------------------------------------------
# Single-process, two-player, no persistence/matchmaking/rooms (later
# tasks) — this is pure "does the real-time pipeline work over a
# network" preparation, now with a minimal username-only login step in
# front of it. One shared GameEngine + GameState, exactly the same
# objects ui/game_factory.py's _new_game() builds for the GUI, just
# driven by parsed algebraic-notation moves from two WebSocket clients
# instead of mouse clicks — but unlike the previous task, that engine
# isn't built at server startup anymore: connecting no longer assigns a
# colour by itself (see GameServer's own docstring). It's built once,
# the moment the second player logs in (see _start_game), which is also
# the moment GameServer.game_ready — an asyncio.Event — gets set;
# run_forever()'s background loops wait on it before they start.
#
# server/ imports from engine/, core/, and ui/ (ui.events for the Bus
# contract + serialization, ui.game_factory for STANDARD_BOARD_ROWS) —
# never the reverse; nothing in engine/, core/, or ui/ imports anything
# from server/.
#
# Wire protocol (JSON, one message per WebSocket text frame):
#
#   Client -> server:
#     {"type": "login", "username": "<name>"}
#     {"type": "move", "from": "e2", "to": "e4"}
#
#   Server -> client, replying to "login":
#     {"type": "login_ok", "color": "white"}              -- or "black"
#     {"type": "login_rejected", "reason": "..."}          -- server already has
#                                                              two logged-in
#                                                              players; connection
#                                                              is closed right
#                                                              after this is sent
#
#   Server -> client, ongoing:
#     {"type": "error", "message": "..."}                  -- reply to a bad
#                                                              command (malformed
#                                                              JSON/username,
#                                                              logging in twice,
#                                                              any non-login
#                                                              message before
#                                                              logging in, an
#                                                              illegal move, a
#                                                              move before the
#                                                              second player has
#                                                              logged in, ...),
#                                                              sent only to the
#                                                              client that sent it
#     {"type": "<GameEvent subclass name>", ...}           -- every event
#                                                              GameEngine fires,
#                                                              once the game has
#                                                              started, serialized
#                                                              via GameEvent.to_dict()
#                                                              (see ui/events.py),
#                                                              broadcast to both
#                                                              clients
#     {"type": "snapshot", "board": [...], "current_time": int,
#      "game_over": bool, "winner": "w"|"b"|null}          -- full-board resync,
#                                                              broadcast once per
#                                                              tick once the game
#                                                              has started (see
#                                                              GameServer._tick_loop)
# ---------------------------------------------------------------------------

TICK_INTERVAL_S = 0.03  # 30ms -- matches main_gui.py's own render-loop cadence
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765
MAX_USERNAME_LENGTH = 32


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
    """Owns the one shared game session and every connected client.

    Two phases:

    1. **Waiting for players** — connecting alone assigns nothing.
       A connection must send ``{"type": "login", "username": "..."}``
       (see ``_handle_login``); the first successful login becomes
       White, the second Black, and a third arriving while both slots
       are taken gets ``login_rejected`` and is closed (a real
       waiting-room/spectator flow is a later "Rooms" task, not this
       one). No password, no persistence, no uniqueness check on
       ``username`` — just non-empty and not absurdly long.

    2. **Playing** — the instant the second login succeeds, ``board``/
       ``state``/``engine`` are actually built (see ``_start_game``,
       previously done unconditionally in ``__init__``) and
       ``game_ready`` (an ``asyncio.Event``) is set. ``run_forever``'s
       background tick/broadcast loops wait on that event before they
       start, so nothing ticks and nothing needing ``engine``/``state``
       runs before both players exist. A move sent by an already-logged-in
       player before the second login is rejected with a plain ``error``
       (see ``_handle_move``) rather than crashing on ``None``.

    Slots free up on disconnect so a later connection can take a
    vacated one — there's still no real matchmaking/reconnection
    identity (later task), just "don't permanently wedge a slot shut".
    """

    def __init__(self) -> None:
        self.board: Optional[TextBoard] = None
        self.state: Optional[GameState] = None
        self.engine: Optional[GameEngine] = None

        self._broadcast_queue: "asyncio.Queue[dict]" = asyncio.Queue()

        self._white: Optional[ServerConnection] = None
        self._black: Optional[ServerConnection] = None
        self._usernames: Dict[ServerConnection, str] = {}

        self.game_ready = asyncio.Event()
        """Set exactly once, by _start_game, the moment both players
        have logged in — see this class's own docstring."""

    # ------------------------------------------------------------------
    # Colour-slot bookkeeping
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

    def _color_for(self, websocket: ServerConnection) -> Optional[Color]:
        """The colour *websocket* is logged in as, or None if it hasn't
        logged in (yet, or ever)."""
        if self._white is websocket:
            return Color.WHITE
        if self._black is websocket:
            return Color.BLACK
        return None

    def _connections(self) -> List[ServerConnection]:
        return [ws for ws in (self._white, self._black) if ws is not None]

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def handler(self, websocket: ServerConnection) -> None:
        """Per-connection entry point registered with ``websockets.serve``.

        Connecting alone does nothing but open the socket — every
        incoming message is dispatched by ``_handle_message`` until this
        client logs in, moves, or disconnects.
        """
        logger.info("Connection opened")
        try:
            async for raw in websocket:
                await self._handle_message(websocket, raw)
        except ConnectionClosed:
            pass
        finally:
            color = self._color_for(websocket)
            self._release_color(websocket)
            self._usernames.pop(websocket, None)
            if color is not None:
                logger.info("Player disconnected (%s)", color.value)
            else:
                logger.info("Connection closed (never logged in)")

    # ------------------------------------------------------------------
    # Incoming messages
    # ------------------------------------------------------------------

    async def _handle_message(self, websocket: ServerConnection, raw: str) -> None:
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

        message_type = message.get("type")
        if message_type == "login":
            await self._handle_login(websocket, message)
            return

        color = self._color_for(websocket)
        if color is None:
            await self._send_error(websocket, "You must log in before sending other commands")
            return

        if message_type == "move":
            await self._handle_move(websocket, color, message)
        else:
            await self._send_error(websocket, f"Unknown message type: {message_type!r}")

    async def _handle_login(self, websocket: ServerConnection, message: dict) -> None:
        if self._color_for(websocket) is not None:
            await self._send_error(websocket, "Already logged in")
            return

        username = message.get("username")
        if not isinstance(username, str) or not username.strip():
            await self._send_error(websocket, "Username must be a non-empty string")
            return
        if len(username) > MAX_USERNAME_LENGTH:
            await self._send_error(
                websocket, f"Username must be at most {MAX_USERNAME_LENGTH} characters"
            )
            return

        color = self._assign_color(websocket)
        if color is None:
            await self._send(websocket, {
                "type": "login_rejected",
                "reason": "Server already has two players logged in.",
            })
            await websocket.close()
            return

        self._usernames[websocket] = username
        logger.info("Login: %r as %s", username, color.value)
        await self._send(websocket, {
            "type": "login_ok",
            "color": "white" if color is Color.WHITE else "black",
        })

        if self._white is not None and self._black is not None:
            self._start_game()

    def _start_game(self) -> None:
        """Build the shared GameEngine/GameState now that both players
        have logged in, and signal ``game_ready`` — called exactly once,
        synchronously, right after the second successful login (see
        ``_handle_login``). Mirrors what the previous task's
        ``GameServer.__init__`` did unconditionally at construction time
        — see this class's own docstring for why that moved here.
        """
        self.board = TextBoard(STANDARD_BOARD_ROWS)
        self.state = GameState(board=self.board)
        self.engine = GameEngine(self.board)
        self.engine.add_observer(_BroadcastObserver(self._broadcast_queue))
        logger.info("Both players logged in -- game started")
        self.game_ready.set()

    async def _handle_move(self, websocket: ServerConnection, color: Color, message: dict) -> None:
        if self.engine is None or self.state is None:
            await self._send_error(
                websocket, "The game hasn't started yet -- waiting for the second player to log in"
            )
            return

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

        Only ever runs after ``run_forever`` has awaited ``game_ready``,
        so ``self.engine``/``self.state`` are guaranteed built by then.
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
        """Wait for both players to log in (see ``game_ready``/
        ``_start_game``), then run the tick loop and the broadcast-drain
        loop concurrently, forever — call once, after the WebSocket
        listener is up. Nothing in either loop touches ``engine``/
        ``state``/``board`` before ``game_ready`` is set, so neither
        loop may start before then.
        """
        await self.game_ready.wait()
        await asyncio.gather(self._tick_loop(), self._broadcast_loop())


async def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    server = GameServer()
    async with serve(server.handler, host, port):
        logger.info(
            "Kung Fu Chess server listening on ws://%s:%d -- waiting for two players to log in",
            host,
            port,
        )
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
