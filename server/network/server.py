from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Callable, Dict, Optional, Type

from shared.constants import DEFAULT_HOST
from shared.models.color import Color
from shared.models.board import TextBoard
from shared.protocol.messages import (
    AckMessage,
    CreateRoomMessage,
    ErrorMessage,
    GameOverMessage,
    GameStateUpdateMessage,
    JoinRoomMessage,
    LoginMessage,
    Message,
    MovePieceMessage,
    QueueForMatchMessage,
    RegisterMessage,
)
from shared.protocol.protocol import Protocol, ProtocolError
from engine.game import GameEngine
from engine.game_state import GameState
from ui.events import GameEvent, GameOverEvent, Observer
from ui.game_factory import STANDARD_BOARD_ROWS
from server.database.sqlite_db_manager import DEFAULT_DB_PATH
from server.game.real_time_arbiter import RealTimeArbiter
from server.services.auth_service import AuthService
from server.services.matchmaking_service import MatchmakingService
from server.services.room_service import JoinOutcome, Room, RoomService, RoomStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kung Fu Chess – Network Server (socket-based, room/matchmaking-capable)
# ---------------------------------------------------------------------------
# A threaded TCP socket server: one thread accepts connections, one
# thread per connected client blocks reading framed Messages (see
# shared.protocol.protocol.Protocol) and routes them by MessageType to
# the Auth/Room/Game handler responsible. Threaded rather than asyncio
# because shared.protocol.protocol.Protocol is built on plain blocking
# ``socket.socket`` calls (``sendall``/``recv``), not an async
# transport — mixing that with an asyncio event loop would mean
# blocking the loop itself on every read.
#
# This is a NEW, ADDITIVE server, deliberately separate from
# server/server.py's existing GameServer (WebSocket-based, no rooms —
# see that module's own docstring: "no persistence/matchmaking/rooms
# (later task)"). server/server.py, network_client.py, and
# main_gui.py's --username mode are UNCHANGED and keep working exactly
# as before; this module does not replace or touch any of them. The
# two servers speak different wire protocols over different
# transports (WebSocket + ad hoc JSON vs. raw TCP + shared.protocol's
# length-prefixed framing) and are not interchangeable — do not run
# both against the same client. Reuses, rather than re-derives, three
# components built in prior iterations for exactly this purpose:
# server.services.auth_service.AuthService (real, database-backed
# accounts), server.game.real_time_arbiter.RealTimeArbiter (per-game
# real-time orchestration), and shared.protocol (the wire format this
# server actually speaks).
#
# Message routing (Auth / Room / Game):
#   Auth : LoginMessage, RegisterMessage
#   Room : CreateRoomMessage, JoinRoomMessage, QueueForMatchMessage
#          (matchmaking finds an opponent and auto-creates/joins a room
#          — see MatchmakingService)
#   Game : MovePieceMessage
#
# A room starts its game (GameEngine + GameState + RealTimeArbiter, one
# set per room, plus a dedicated tick-loop thread) the instant it
# reaches RoomService.MAX_PLAYERS (2) — mirroring GameServer's own
# "game starts on the second login" convention, generalized to happen
# per room instead of once globally. Every GameEvent the game produces
# triggers a fresh GameStateUpdateMessage broadcast to both of that
# room's connections; a GameOverEvent additionally sends a
# GameOverMessage.
#
# Concurrency: one coarse-grained ``threading.RLock`` guards every
# piece of this class's own shared mutable state (connections, rooms,
# games, matchmaking queue) — simple and correct-by-construction,
# appropriate at this scale (a handful of concurrent two-player games,
# not a high-throughput production matchmaking service).
# ---------------------------------------------------------------------------

DEFAULT_PORT = 8766  # distinct from shared.constants.DEFAULT_PORT (8765) --
                     # server/server.py's own default -- so the two servers
                     # never collide if both happen to run on one host.
TICK_INTERVAL_S = 0.03  # matches server/server.py's own tick cadence


class ClientConnection:
    """One connected socket plus its session state.

    ``username`` is ``None`` until a successful ``LoginMessage``;
    ``room_id`` is ``None`` until the connection has joined (or been
    matched into) a room. ``send_lock`` serializes writes to ``sock``
    — both this connection's own handler thread and a game's broadcast
    (from a different room's tick-loop thread) may send to it.
    """

    def __init__(self, sock: socket.socket, address: object) -> None:
        self.sock = sock
        self.address = address
        self.username: Optional[str] = None
        self.room_id: Optional[str] = None
        self.elo_rating: int = 0
        self.send_lock = threading.Lock()


class _RoomGame:
    """One room's running game: its ``RealTimeArbiter`` plus everything
    needed to broadcast to (and stop) it."""

    def __init__(
        self,
        room_id: str,
        arbiter: RealTimeArbiter,
        colors: Dict[str, Color],
        connections: Dict[str, ClientConnection],
    ) -> None:
        self.room_id = room_id
        self.arbiter = arbiter
        self.colors = colors
        self.connections = connections
        self.stop_event = threading.Event()
        self.tick_thread: Optional[threading.Thread] = None


class _RoomBroadcastObserver(Observer):
    """Bridges ``GameEngine``'s synchronous ``Observer`` callback to a
    broadcast: every event triggers a fresh board-state broadcast to
    the room's connections, and a ``GameOverEvent`` additionally sends
    a ``GameOverMessage``. Mirrors server/server.py's own
    ``_BroadcastObserver`` in spirit, adapted for a per-room game
    rather than one global one, and for shared.protocol's message
    types rather than raw dicts.
    """

    def __init__(self, server: "NetworkServer", room_game: _RoomGame) -> None:
        self._server = server
        self._room_game = room_game

    def on_event(self, event: GameEvent) -> None:
        self._server._broadcast_snapshot(self._room_game)
        if isinstance(event, GameOverEvent):
            self._server._broadcast_game_over(self._room_game)


class NetworkServer:
    """Threaded TCP socket server for room/matchmaking-based, real-time,
    multi-room Kung Fu Chess."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        db_path: str = DEFAULT_DB_PATH,
    ) -> None:
        self._host = host
        self._port = port
        self._auth = AuthService(db_path=db_path)
        self._rooms = RoomService()
        self._matchmaking = MatchmakingService()

        self._lock = threading.RLock()
        self._connections_by_username: Dict[str, ClientConnection] = {}
        self._games: Dict[str, _RoomGame] = {}

        self._server_socket: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Dispatch tables for _route(): message class -> handler. Split
        # in two because Login/Register are the only messages allowed
        # before a connection has logged in -- everything else needs
        # the login-gate check in between (see _route). Built once,
        # here, as bound methods, rather than a growing isinstance/elif
        # chain in _route itself -- adding a new message type only ever
        # means adding one entry to one of these dicts.
        self._login_exempt_handlers: Dict[Type[Message], Callable[[ClientConnection, Message], None]] = {
            LoginMessage: self._handle_login,
            RegisterMessage: self._handle_register,
        }
        self._authenticated_handlers: Dict[Type[Message], Callable[[ClientConnection, Message], None]] = {
            CreateRoomMessage: self._handle_create_room,
            JoinRoomMessage: self._handle_join_room,
            QueueForMatchMessage: self._handle_queue_for_match,
            MovePieceMessage: self._handle_move_piece,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Bind, listen, and start accepting connections in a background
        thread — returns immediately; call ``stop()`` to shut down."""
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self._host, self._port))
        self._server_socket.listen()
        logger.info("NetworkServer listening on %s:%d", self._host, self._port)

        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    def stop(self) -> None:
        """Stop accepting new connections, tear down every running
        room game, and wait for the accept thread to exit."""
        self._stop_event.set()
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                # Already closed (e.g. stop() called twice, or the socket
                # was never successfully bound) -- closing twice is not an
                # error condition worth surfacing, there's nothing left to
                # clean up either way.
                pass
        with self._lock:
            for room_game in self._games.values():
                room_game.stop_event.set()
            self._games.clear()
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=2.0)

    def _accept_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                client_sock, address = self._server_socket.accept()
            except OSError:
                break  # listening socket closed by stop()
            connection = ClientConnection(client_sock, address)
            logger.info("Connection opened: %s", address)
            threading.Thread(
                target=self._client_loop, args=(connection,), daemon=True
            ).start()

    def _client_loop(self, connection: ClientConnection) -> None:
        try:
            while True:
                message = Protocol.receive(connection.sock)
                self._route(connection, message)
        except OSError:
            # The connection was closed or reset -- an ordinary
            # disconnect (client quit, network drop, or our own
            # socket being closed by stop()/_on_disconnect elsewhere).
            # Nothing to log beyond what _on_disconnect already logs.
            pass
        except ProtocolError as e:
            # Unlike a plain disconnect, this means the peer sent bytes
            # that don't decode as a valid framed message -- a client
            # bug, a version mismatch, or a non-protocol connection
            # (e.g. a port scanner). Worth knowing about even though we
            # still just drop the connection the same way.
            logger.warning("Malformed message from %s: %s", connection.address, e)
        finally:
            self._on_disconnect(connection)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _route(self, connection: ClientConnection, message: Message) -> None:
        login_exempt_handler = self._login_exempt_handlers.get(type(message))
        if login_exempt_handler is not None:
            login_exempt_handler(connection, message)
            return

        if connection.username is None:
            self._send(connection, ErrorMessage(message="You must log in before sending other commands"))
            return

        handler = self._authenticated_handlers.get(type(message))
        if handler is None:
            self._send(
                connection,
                ErrorMessage(message=f"Unexpected message type from client: {type(message).__name__}"),
            )
            return
        handler(connection, message)

    # ------------------------------------------------------------------
    # Auth handlers
    # ------------------------------------------------------------------

    def _handle_register(self, connection: ClientConnection, message: RegisterMessage) -> None:
        result = self._auth.register(message.username, message.password)
        if not result.outcome.is_ok:
            self._send(connection, ErrorMessage(message=f"Registration failed: {result.outcome.name}"))
            return
        self._send(
            connection,
            AckMessage(request_type="register", detail={"user_id": str(result.user.user_id)}),
        )

    def _handle_login(self, connection: ClientConnection, message: LoginMessage) -> None:
        if connection.username is not None:
            self._send(connection, ErrorMessage(message="Already logged in"))
            return

        result = self._auth.login(message.username, message.password)
        if not result.outcome.is_ok:
            self._send(connection, ErrorMessage(message=f"Login failed: {result.outcome.name}"))
            return

        connection.username = message.username
        connection.elo_rating = result.user.elo_rating
        with self._lock:
            self._connections_by_username[message.username] = connection
        logger.info("Login: %r (elo=%d)", message.username, result.user.elo_rating)
        self._send(
            connection,
            AckMessage(request_type="login", detail={"elo_rating": str(result.user.elo_rating)}),
        )

    # ------------------------------------------------------------------
    # Room handlers
    # ------------------------------------------------------------------

    def _handle_create_room(self, connection: ClientConnection, message: CreateRoomMessage) -> None:
        with self._lock:
            room = self._rooms.create_room(message.room_name)
            self._rooms.join_room(room.room_id, connection.username)  # creator auto-joins
            connection.room_id = room.room_id
        logger.info("Room %r (%s) created by %r", room.room_id, message.room_name, connection.username)
        self._send(connection, AckMessage(request_type="create_room", detail={"room_id": room.room_id}))

    def _handle_join_room(self, connection: ClientConnection, message: JoinRoomMessage) -> None:
        with self._lock:
            outcome = self._rooms.join_room(message.room_id, connection.username)
            if not outcome.is_ok:
                self._send(connection, ErrorMessage(message=f"Could not join room: {outcome.name}"))
                return
            connection.room_id = message.room_id
            room = self._rooms.get_room(message.room_id)

        self._send(connection, AckMessage(request_type="join_room", detail={"room_id": message.room_id}))
        if room is not None and room.status is RoomStatus.READY:
            self._start_game(room)

    def _handle_queue_for_match(self, connection: ClientConnection, message: QueueForMatchMessage) -> None:
        with self._lock:
            self._matchmaking.enqueue(connection.username, connection.elo_rating)
            pairing = self._matchmaking.find_match()
            if pairing is None:
                self._send(connection, AckMessage(request_type="queue_for_match", detail={"status": "queued"}))
                return

            room = self._rooms.create_room(
                f"Match: {pairing.player_a.username} vs {pairing.player_b.username}"
            )
            self._rooms.join_room(room.room_id, pairing.player_a.username)
            self._rooms.join_room(room.room_id, pairing.player_b.username)
            matched_usernames = (pairing.player_a.username, pairing.player_b.username)
            for username in matched_usernames:
                matched_connection = self._connections_by_username.get(username)
                if matched_connection is not None:
                    matched_connection.room_id = room.room_id

        logger.info("Matched %r vs %r -> room %r", *matched_usernames, room.room_id)
        for username in matched_usernames:
            matched_connection = self._connections_by_username.get(username)
            if matched_connection is not None:
                self._send(
                    matched_connection,
                    AckMessage(
                        request_type="queue_for_match",
                        detail={"status": "matched", "room_id": room.room_id},
                    ),
                )
        self._start_game(room)

    # ------------------------------------------------------------------
    # Game lifecycle
    # ------------------------------------------------------------------

    def _start_game(self, room: Room) -> None:
        """Build a fresh GameEngine/GameState/RealTimeArbiter for *room*
        (exactly 2 players joined; see RoomService.join_room) and start
        its tick-loop thread. Called once per room, the instant its
        second player joins.
        """
        board = TextBoard(STANDARD_BOARD_ROWS)
        state = GameState(board=board)
        engine = GameEngine(board)
        arbiter = RealTimeArbiter(engine, state)

        colors = {room.players[0]: Color.WHITE, room.players[1]: Color.BLACK}
        with self._lock:
            connections = {
                username: self._connections_by_username[username]
                for username in room.players
                if username in self._connections_by_username
            }
            room_game = _RoomGame(room.room_id, arbiter, colors, connections)
            arbiter.add_observer(_RoomBroadcastObserver(self, room_game))
            self._games[room.room_id] = room_game
            self._rooms.start(room.room_id)

        logger.info("Game started for room %r: %s", room.room_id, colors)
        room_game.tick_thread = threading.Thread(
            target=self._tick_loop, args=(room_game,), daemon=True
        )
        room_game.tick_thread.start()

    def _tick_loop(self, room_game: _RoomGame) -> None:
        while not room_game.stop_event.is_set():
            time.sleep(TICK_INTERVAL_S)
            if room_game.stop_event.is_set():
                break
            room_game.arbiter.advance(int(TICK_INTERVAL_S * 1000))

    def _handle_move_piece(self, connection: ClientConnection, message: MovePieceMessage) -> None:
        if connection.room_id is None:
            self._send(connection, ErrorMessage(message="You must join a room before moving"))
            return

        with self._lock:
            room_game = self._games.get(connection.room_id)
        if room_game is None:
            self._send(connection, ErrorMessage(message="This room's game hasn't started yet"))
            return

        color = room_game.colors.get(connection.username)
        piece = room_game.arbiter.state.board.get_piece_at(message.from_cell)
        # Real-time gameplay has no turn order (either side may move
        # anytime), but a connection must still only ever move ITS OWN
        # colour's pieces -- mirrors server/server.py's own
        # _handle_move guard exactly.
        if piece is None or piece == "." or color is None or piece[0] != color.value:
            self._send(connection, ErrorMessage(message=f"You do not control the piece at {message.from_cell!r}"))
            return

        legality = room_game.arbiter.submit_move(message.from_cell, message.to_cell)
        if not legality.is_ok:
            self._send(connection, ErrorMessage(message=f"Illegal move: {legality.name}"))

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------

    def _broadcast_snapshot(self, room_game: _RoomGame) -> None:
        state = room_game.arbiter.state
        message = GameStateUpdateMessage(board=tuple(state.board.get_rows()), current_time=state.current_time)
        self._broadcast(room_game, message)

    def _broadcast_game_over(self, room_game: _RoomGame) -> None:
        winner = room_game.arbiter.state.winner
        message = GameOverMessage(winner=winner.value if winner is not None else None)
        self._broadcast(room_game, message)

    def _broadcast(self, room_game: _RoomGame, message: Message) -> None:
        for connection in room_game.connections.values():
            self._send(connection, message)

    def _send(self, connection: ClientConnection, message: Message) -> None:
        with connection.send_lock:
            try:
                Protocol.send(connection.sock, message)
            except OSError:
                logger.info("Send failed to %s (disconnected)", connection.address)

    # ------------------------------------------------------------------
    # Disconnection
    # ------------------------------------------------------------------

    def _on_disconnect(self, connection: ClientConnection) -> None:
        with self._lock:
            if connection.username is not None:
                self._connections_by_username.pop(connection.username, None)
                self._matchmaking.dequeue(connection.username)
                if connection.room_id is not None:
                    self._rooms.leave_room(connection.room_id, connection.username)
                    room_game = self._games.get(connection.room_id)
                    if room_game is not None:
                        room_game.connections.pop(connection.username, None)
                        if not room_game.connections:
                            room_game.stop_event.set()
                            self._games.pop(connection.room_id, None)
                logger.info("Connection closed: %r", connection.username)
            else:
                logger.info("Connection closed (never logged in): %s", connection.address)
        try:
            connection.sock.close()
        except OSError:
            # Already closed (the read loop's own OSError already means
            # the socket is in a bad/closed state) -- nothing further to
            # clean up, and nothing new to report.
            pass
