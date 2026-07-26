from __future__ import annotations

import logging
import queue
import socket
import threading
from typing import List, Optional

from shared.models.cell import Cell
from shared.protocol.messages import (
    CreateRoomMessage,
    JoinRoomMessage,
    LoginMessage,
    Message,
    MovePieceMessage,
    QueueForMatchMessage,
    RegisterMessage,
)
from shared.protocol.protocol import Protocol, ProtocolError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kung Fu Chess – Client Network Layer (client <-> server/network/server.py)
# ---------------------------------------------------------------------------
# The socket-based counterpart to the root network_client.py (which
# talks to server/server.py over WebSockets/asyncio, using its own ad
# hoc JSON wire format). This class talks to server/network/server.py
# instead, over a raw, blocking TCP socket, using shared.protocol's
# framed Message objects — the two are not interchangeable and this
# class does not touch or replace network_client.py.
#
# Two background threads, not one, because shared.protocol.protocol.
# Protocol is built on plain blocking socket calls (send/recv), and one
# thread can't simultaneously block on "read the next incoming
# message" and "write the next outgoing one" without either
# non-blocking sockets or select() — two threads is the simpler
# option. Same spirit as root network_client.py running a receive
# task and a send task concurrently on its own asyncio event loop —
# just OS threads instead of asyncio tasks, since this transport is a
# plain blocking socket, not an async one.
#
#   * ``_receive_loop`` — blocks on ``Protocol.receive(sock)`` in a
#     loop, appending every arriving ``Message`` to a thread-safe list
#     the caller drains via ``pop_messages()``.
#   * ``_send_loop`` — blocks on a ``queue.Queue.get()``, writing each
#     queued ``Message`` via ``Protocol.send(sock, message)`` — so
#     ``send()`` itself never blocks the calling (GUI) thread on the
#     socket write.
#
# No chess/auth/room logic of its own — purely transport. Interpreting
# *which* Message arrived (an Ack, an Error, a board snapshot, ...) and
# reacting to it is client.ui.app.online_coordinator.OnlineCoordinator's
# job, not this class's.
# ---------------------------------------------------------------------------

_STOP = object()  # sentinel pushed onto the send queue to end _send_loop


class NetworkClient:
    """One TCP connection to ``server/network/server.py``.

    Usage (from the GUI/main thread)::

        client = NetworkClient(host, port)
        if not client.connect(timeout=5.0):
            ...  # connection failed -- see is_connected()
        client.login("alice", "hunter2")     # non-blocking
        for message in client.pop_messages(): # non-blocking, polled once/frame
            ...
        client.close()
    """

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port

        self._sock: Optional[socket.socket] = None
        self._receive_thread: Optional[threading.Thread] = None
        self._send_thread: Optional[threading.Thread] = None
        self._send_queue: "queue.Queue[object]" = queue.Queue()

        self._lock = threading.Lock()
        self._connected = False
        self._pending_messages: List[Message] = []
        self._closed = False

    # ------------------------------------------------------------------
    # Public, thread-safe API -- called from the GUI thread
    # ------------------------------------------------------------------

    def connect(self, timeout: float = 5.0) -> bool:
        """Open the TCP connection and start both background threads.

        Returns True on success, False iff the connection itself
        failed (refused, timed out, unreachable host, ...) — nothing
        past the raw TCP connect is validated here; a bad login is
        reported later, as an ``ErrorMessage`` via ``pop_messages()``,
        exactly like any other server-side rejection.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((self._host, self._port))
        except OSError as e:
            logger.info("Connection to %s:%d failed: %s", self._host, self._port, e)
            return False
        sock.settimeout(None)  # blocking mode for the receive loop's long-lived reads

        self._sock = sock
        with self._lock:
            self._connected = True

        self._receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._receive_thread.start()
        self._send_thread.start()
        return True

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    def pop_messages(self) -> List[Message]:
        """Every ``Message`` received since the last call, and clear
        them — the caller (typically ``OnlineCoordinator``) polls this
        once per frame and dispatches by ``isinstance``."""
        with self._lock:
            messages, self._pending_messages = self._pending_messages, []
            return messages

    def send(self, message: Message) -> None:
        """Queue *message* for the background send thread — never
        blocks the calling thread on the socket write itself. Silently
        dropped if not currently connected."""
        if not self.is_connected():
            return
        self._send_queue.put(message)

    def close(self) -> None:
        """Stop both background threads and close the socket. Safe to
        call more than once (a no-op after the first)."""
        if self._closed:
            return
        self._closed = True
        self._send_queue.put(_STOP)
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        for thread in (self._receive_thread, self._send_thread):
            if thread is not None:
                thread.join(timeout=2.0)
        with self._lock:
            self._connected = False

    # ------------------------------------------------------------------
    # Convenience wrappers -- one per outgoing action, so a caller never
    # has to construct shared.protocol.messages objects itself.
    # ------------------------------------------------------------------

    def register(self, username: str, password: str) -> None:
        self.send(RegisterMessage(username=username, password=password))

    def login(self, username: str, password: str) -> None:
        self.send(LoginMessage(username=username, password=password))

    def create_room(self, room_name: str) -> None:
        self.send(CreateRoomMessage(room_name=room_name))

    def join_room(self, room_id: str) -> None:
        self.send(JoinRoomMessage(room_id=room_id))

    def queue_for_match(self) -> None:
        self.send(QueueForMatchMessage())

    def move_piece(self, from_cell: Cell, to_cell: Cell, piece_id: str) -> None:
        self.send(MovePieceMessage(from_cell=from_cell, to_cell=to_cell, piece_id=piece_id))

    # ------------------------------------------------------------------
    # Background thread bodies
    # ------------------------------------------------------------------

    def _receive_loop(self) -> None:
        try:
            while True:
                message = Protocol.receive(self._sock)
                with self._lock:
                    self._pending_messages.append(message)
        except (ProtocolError, OSError):
            pass
        finally:
            with self._lock:
                self._connected = False

    def _send_loop(self) -> None:
        while True:
            message = self._send_queue.get()
            if message is _STOP:
                return
            try:
                Protocol.send(self._sock, message)
            except OSError:
                with self._lock:
                    self._connected = False
                return
