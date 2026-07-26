from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from typing import List, Optional

from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

from core.models import Position
from server.algebraic import position_to_algebraic

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kung Fu Chess – Network client (main_gui.py <-> server/server.py)
# ---------------------------------------------------------------------------
# Bridges main_gui.py's synchronous, cv2-driven render loop
# (cv2.imshow/cv2.waitKey polling, no asyncio anywhere in it) to
# server/server.py's asyncio/websockets protocol: runs its own asyncio
# event loop in a background thread, rather than rewriting main_gui.py's
# whole render loop to be asyncio-native — that would touch every
# existing local-mode code path (_run_single_player/_run_two_player) for
# a feature that's purely additive to them.
#
# Every cross-thread handoff goes through either a threading.Lock (the
# small bit of inbound state the GUI thread polls once per frame:
# latest snapshot, queued errors/events, connection status) or an
# asyncio.Queue fed via loop.call_soon_threadsafe (outbound moves) — the
# background thread never touches anything the GUI thread owns, and
# vice versa.
#
# Deliberately does NOT reconstruct a full engine.snapshot.GameSnapshot
# (pending moves/airborne jumps/cooldowns): server/server.py's current
# wire protocol's "snapshot" message only carries board/current_time/
# game_over/winner (see that module's own header) — nothing per-piece.
# main_gui.py's network mode (ui/game_loop.py's _run_network_player)
# therefore renders the bare board only: no smooth in-transit gliding,
# no cooldown overlays, no local score/move-history tracking. Extending
# the wire protocol to carry that per-piece detail is a separate,
# server-side task, not this one.
#
# The server enforces move legality; this module has no chess logic of
# its own — send_move() is a dumb from_pos/to_pos -> algebraic ->
# {"type": "move", ...} pass-through. Whatever the server does with it
# (queue it, reject it, ignore it) shows up in a later "snapshot"/
# "error" message, never as an immediate local effect.
# ---------------------------------------------------------------------------


class NetworkClient:
    """One WebSocket connection to ``server/server.py``, run on a
    background thread's own asyncio event loop.

    Usage (from the GUI/main thread)::

        client = NetworkClient(host, port, username)
        color = client.connect(timeout=5.0)   # blocks until login resolves
        if color is None:
            ...  # rejected or failed to connect -- see pop_errors()
        ...
        client.send_move(from_pos, to_pos)      # non-blocking
        snapshot = client.get_latest_snapshot() # non-blocking, may be None
        for message in client.pop_errors():
            ...
        client.close()

    ``send_move``/``get_latest_snapshot``/``pop_errors``/``pop_events``/
    ``is_connected`` are only meaningful after ``connect()`` has
    returned a non-``None`` colour — calling them before that (while no
    background loop/queue exists yet) is harmless (send_move silently
    drops the message; the getters return empty/None), just pointless.
    """

    def __init__(self, host: str, port: int, username: str) -> None:
        self._host = host
        self._port = port
        self._username = username

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._outbound: Optional[asyncio.Queue] = None

        self._lock = threading.Lock()
        self._connected = False
        self._latest_snapshot: Optional[dict] = None
        self._pending_errors: List[str] = []
        self._pending_events: List[dict] = []

        self._login_result: "queue.Queue[Optional[str]]" = queue.Queue(maxsize=1)
        self._closed = False

    # ------------------------------------------------------------------
    # Public, thread-safe API -- called from the GUI thread
    # ------------------------------------------------------------------

    def connect(self, timeout: float = 5.0) -> Optional[str]:
        """Start the background event loop, connect, log in as
        *username*, and block the calling (GUI) thread until the server
        replies to the login attempt.

        Returns the assigned colour (``"white"``/``"black"``) on
        success, or ``None`` if the connection failed, the login
        attempt timed out, or the server sent ``login_rejected`` instead
        — see ``pop_errors()`` for why.
        """
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()
        try:
            return self._login_result.get(timeout=timeout)
        except queue.Empty:
            with self._lock:
                self._pending_errors.append("Timed out waiting for the server.")
            return None

    def send_move(self, from_pos: Position, to_pos: Position) -> None:
        """Queue a move message for the background loop to send.

        Never blocks, never mutates any local board state — the server
        is the sole authority on whether this move is legal (see this
        module's own header); any effect only ever shows up later, via
        a broadcast ``snapshot``/``MoveCompletedEvent``, or is reported
        back as an ``error`` if rejected.
        """
        message = {
            "type": "move",
            "from": position_to_algebraic(from_pos),
            "to": position_to_algebraic(to_pos),
        }
        if self._loop is not None and self._outbound is not None:
            self._loop.call_soon_threadsafe(self._outbound.put_nowait, message)

    def get_latest_snapshot(self) -> Optional[dict]:
        """The most recently received ``"snapshot"`` message (a plain
        dict, exactly as the server sent it), or ``None`` if none has
        arrived yet."""
        with self._lock:
            return self._latest_snapshot

    def pop_errors(self) -> List[str]:
        """Every ``"error"``/``"login_rejected"``/connection-failure
        message received since the last call, and clear them — the GUI
        calls this once per frame."""
        with self._lock:
            errors, self._pending_errors = self._pending_errors, []
            return errors

    def pop_events(self) -> List[dict]:
        """Every other server message received since the last call
        (``MoveCompletedEvent``, ``GameOverEvent``, ``TimeAdvancedEvent``,
        ...), and clear them. Not yet consumed by anything in
        main_gui.py's network mode — exposed for a future caller (e.g.
        sound triggers) rather than silently dropped."""
        with self._lock:
            events, self._pending_events = self._pending_events, []
            return events

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    def close(self) -> None:
        """Signal the background loop to disconnect and stop; blocks
        briefly for the thread to actually exit. Safe to call more than
        once (a no-op after the first)."""
        if self._closed:
            return
        self._closed = True
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    # ------------------------------------------------------------------
    # Background thread body
    # ------------------------------------------------------------------

    def _run_event_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as e:
            logger.exception("Network client background loop failed")
            with self._lock:
                self._connected = False
                self._pending_errors.append(f"Connection error: {e}")
            if self._login_result.empty():
                self._login_result.put(None)
        finally:
            self._loop.close()

    async def _main(self) -> None:
        self._stop_event = asyncio.Event()
        self._outbound = asyncio.Queue()

        url = f"ws://{self._host}:{self._port}"
        async with ws_connect(url) as websocket:
            await websocket.send(json.dumps({"type": "login", "username": self._username}))

            receive_task = asyncio.create_task(self._receive_loop(websocket))
            send_task = asyncio.create_task(self._send_loop(websocket))
            stop_task = asyncio.create_task(self._stop_event.wait())

            await asyncio.wait(
                [receive_task, send_task, stop_task], return_when=asyncio.FIRST_COMPLETED
            )
            for task in (receive_task, send_task, stop_task):
                task.cancel()

    async def _receive_loop(self, websocket) -> None:
        try:
            async for raw in websocket:
                self._handle_incoming(raw)
        except ConnectionClosed:
            pass
        with self._lock:
            self._connected = False
            self._pending_errors.append("Disconnected from server.")
        if self._login_result.empty():
            self._login_result.put(None)

    async def _send_loop(self, websocket) -> None:
        while True:
            message = await self._outbound.get()
            try:
                await websocket.send(json.dumps(message))
            except ConnectionClosed:
                return

    def _handle_incoming(self, raw: str) -> None:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return
        message_type = message.get("type")

        if message_type == "login_ok":
            with self._lock:
                self._connected = True
            if self._login_result.empty():
                self._login_result.put(message.get("color"))
        elif message_type == "login_rejected":
            with self._lock:
                self._pending_errors.append(message.get("reason", "Login rejected."))
            if self._login_result.empty():
                self._login_result.put(None)
        elif message_type == "snapshot":
            with self._lock:
                self._latest_snapshot = message
        elif message_type == "error":
            with self._lock:
                self._pending_errors.append(message.get("message", "Unknown error."))
        else:
            with self._lock:
                self._pending_events.append(message)
