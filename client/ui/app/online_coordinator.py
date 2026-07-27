from __future__ import annotations

from typing import List, Optional, Tuple

from shared.models.cell import Cell
from shared.protocol.messages import (
    AckMessage,
    ErrorMessage,
    GameOverMessage,
    GameStateUpdateMessage,
    Message,
)
from client.network.client import NetworkClient
from client.ui.screens.screen_manager import Screen, ScreenManager

# ---------------------------------------------------------------------------
# Kung Fu Chess – Online Coordinator
# ---------------------------------------------------------------------------
# Bridges client.network.client.NetworkClient's incoming Message
# objects to client.ui.screens.screen_manager.ScreenManager's screen
# transitions, plus a small amount of exposed read-only game state
# (room id, latest board snapshot, game-over/winner, pending errors).
#
# The actual UI (whatever draws Main Menu/Login/Lobby/Game) polls THIS
# class once per frame via ``poll()`` — never NetworkClient directly —
# so it never has to know shared.protocol's message shapes, and never
# has to duplicate the Ack-detail/screen-transition wiring below. This
# is purely a coordinator: it owns no rendering, no window, no input
# handling of its own (compare to root main_gui.py/ui.game_loop.py,
# which mix real-time input handling into the render loop itself —
# this class deliberately stays out of that, so a caller's render loop
# only ever needs one call, ``poll()``, plus the outgoing-action
# methods below).
# ---------------------------------------------------------------------------


class OnlineCoordinator:
    """Owns one ``NetworkClient`` + one ``ScreenManager`` and keeps them
    in sync: every server message ``poll()`` drains either updates
    this class's own exposed state, or drives a screen transition (or
    both) — see ``_handle`` for the full mapping.
    """

    def __init__(self, client: NetworkClient, screens: ScreenManager) -> None:
        self._client = client
        self._screens = screens

        self._elo_rating: Optional[int] = None
        self._room_id: Optional[str] = None
        self._latest_board: Optional[Tuple[str, ...]] = None
        self._current_time: int = 0
        self._game_over = False
        self._winner: Optional[str] = None
        self._pending_errors: List[str] = []

    @property
    def screens(self) -> ScreenManager:
        """The ``ScreenManager`` this coordinator drives — exposed so a
        screen's own run loop can both read ``current`` (to know when
        to return control to its caller) and call ``transition_to``
        directly for a purely local, non-network-driven transition
        (e.g. a "Log Out"/"Back" button — see ``log_out()`` below)."""
        return self._screens

    # ------------------------------------------------------------------
    # Driven once per UI frame
    # ------------------------------------------------------------------

    def poll(self) -> None:
        """Drain every ``Message`` ``NetworkClient`` has received since
        the last call and react — call once per UI frame/tick."""
        for message in self._client.pop_messages():
            self._handle(message)

    def _handle(self, message: Message) -> None:
        if isinstance(message, AckMessage):
            self._handle_ack(message)
        elif isinstance(message, ErrorMessage):
            self._pending_errors.append(message.message)
        elif isinstance(message, GameStateUpdateMessage):
            self._latest_board = message.board
            self._current_time = message.current_time
            # The server only ever starts sending board snapshots once
            # a room reaches its second player (see
            # server.network.server.NetworkServer._start_game) — so the
            # FIRST one to arrive while still in the Lobby is exactly
            # the "your game has started" signal.
            if self._screens.current is Screen.LOBBY:
                self._screens.transition_to(Screen.GAME)
        elif isinstance(message, GameOverMessage):
            self._game_over = True
            self._winner = message.winner

    def _handle_ack(self, message: AckMessage) -> None:
        if message.request_type == "login":
            elo = message.detail.get("elo_rating")
            self._elo_rating = int(elo) if elo is not None else None
            self._screens.transition_to(Screen.LOBBY)
        elif message.request_type in ("create_room", "join_room"):
            self._room_id = message.detail.get("room_id")
        elif message.request_type == "queue_for_match":
            if message.detail.get("status") == "matched":
                self._room_id = message.detail.get("room_id")
            # status == "queued": no room yet -- stay put, wait for a
            # later ack with status == "matched".

    # ------------------------------------------------------------------
    # Read-only state for the UI
    # ------------------------------------------------------------------

    @property
    def elo_rating(self) -> Optional[int]:
        return self._elo_rating

    @property
    def room_id(self) -> Optional[str]:
        return self._room_id

    @property
    def latest_board(self) -> Optional[Tuple[str, ...]]:
        return self._latest_board

    @property
    def current_time(self) -> int:
        return self._current_time

    @property
    def is_game_over(self) -> bool:
        return self._game_over

    @property
    def winner(self) -> Optional[str]:
        return self._winner

    def pop_errors(self) -> List[str]:
        """Every error message received since the last call, and clear
        them — the UI polls this once per frame to display/log them."""
        errors, self._pending_errors = self._pending_errors, []
        return errors

    # ------------------------------------------------------------------
    # Outgoing actions -- thin forwarding to NetworkClient, plus
    # whatever local state a fresh attempt should reset first.
    # ------------------------------------------------------------------

    def register(self, username: str, password: str) -> None:
        self._client.register(username, password)

    def login(self, username: str, password: str) -> None:
        self._client.login(username, password)

    def create_room(self, room_name: str) -> None:
        self._client.create_room(room_name)

    def join_room(self, room_id: str) -> None:
        self._client.join_room(room_id)

    def queue_for_match(self) -> None:
        self._client.queue_for_match()

    def move_piece(self, from_cell: Cell, to_cell: Cell, piece_id: str) -> None:
        self._client.move_piece(from_cell, to_cell, piece_id)

    def return_to_lobby(self) -> None:
        """User-initiated: dismiss a finished game and go back to the
        Lobby — clears this coordinator's own per-game state (room id,
        board, game-over/winner) so a stale value never leaks into the
        next game."""
        self._room_id = None
        self._latest_board = None
        self._current_time = 0
        self._game_over = False
        self._winner = None
        self._screens.transition_to(Screen.LOBBY)

    def log_out(self) -> None:
        """User-initiated: leave the Lobby back to the Main Menu."""
        self._screens.transition_to(Screen.MAIN_MENU)
