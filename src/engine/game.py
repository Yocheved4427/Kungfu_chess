from __future__ import annotations

from typing import List

from src.core.models import Position
from src.engine.board import AbstractBoard
from src.engine.rules import MoveValidator
from src.ui.events import GameEvent, Observer, RenderEvent

# ---------------------------------------------------------------------------
# Kung Fu Chess – Game Engine
# ---------------------------------------------------------------------------
# Patterns
# --------
#   Subject / Observer  – maintains a subscriber list; fires RenderEvent on
#                         request.  Does NOT return or print board strings.
#   Dependency Injection – board and validator are injected, never constructed
#                         internally, keeping this class fully testable.
#
# The engine is rule-agnostic: all chess logic is delegated to MoveValidator.
# ---------------------------------------------------------------------------


class GameEngine:
    """Core game state machine and event Subject.

    Responsibilities
    ----------------
    * Convert pixel coordinates to board cells (``handle_click``).
    * Manage single-piece selection state.
    * Validate moves via ``MoveValidator`` before applying them.
    * Apply legal moves to the board via ``board.move_piece``.
    * Advance the game clock (``wait``).
    * Notify registered ``Observer`` instances on game events.
    """

    def __init__(
        self,
        board: AbstractBoard,
        cell_size: int = 100,
        validator: MoveValidator | None = None,
    ) -> None:
        self.board: AbstractBoard = board
        self.selection: Position | None = None
        self._clock_ms: int = 0
        self._cell_size: int = cell_size
        self._validator: MoveValidator = (
            validator if validator is not None else MoveValidator()
        )
        self._observers: List[Observer] = []

    # ------------------------------------------------------------------
    # Subject interface
    # ------------------------------------------------------------------

    def add_observer(self, observer: Observer) -> None:
        """Register *observer* to receive future ``GameEvent`` notifications."""
        self._observers.append(observer)

    def _notify(self, event: GameEvent) -> None:
        for obs in self._observers:
            obs.on_event(event)

    def request_render(self) -> None:
        """Broadcast a ``RenderEvent`` carrying the current board text.

        Callers request a render; the engine publishes it.  The engine never
        returns board strings directly — observers handle all output.
        """
        self._notify(RenderEvent(board_text=self.board.render()))

    # ------------------------------------------------------------------
    # Game commands
    # ------------------------------------------------------------------

    def handle_click(self, x: int, y: int) -> None:
        """Process a pixel-coordinate click.

        Coordinate mapping
        ------------------
        ``col = x // cell_size``,  ``row = y // cell_size``

        State machine
        -------------
        * Out-of-bounds click → silently ignored.
        * No selection, click on empty square → silently ignored.
        * No selection, click on piece → piece selected.
        * Selection exists, click on friendly piece → selection replaced (no move
          attempted; ``MoveValidator`` is never called in this branch).
        * Selection exists, click on empty or enemy cell:
            - Legal move  → ``board.move_piece`` applied; enemy piece on
              destination is overwritten (capture). Selection cleared.
            - Illegal move (wrong shape, blocked path) → board unchanged
              (silent failure). Selection cleared.
        """
        col = x // self._cell_size
        row = y // self._cell_size

        if not (0 <= row < self.board.num_rows and 0 <= col < self.board.num_cols):
            return

        pos = Position(row, col)
        clicked_piece = self.board.get_piece_at(pos)

        if self.selection is None:
            if clicked_piece != ".":
                self.selection = pos
            return

        selected_piece = self.board.get_piece_at(self.selection)

        # Re-select a different friendly piece.
        if clicked_piece != "." and self._is_friendly(selected_piece, clicked_piece):
            self.selection = pos
            return

        # Attempt move — selection always cleared after this point.
        if self._validator.is_valid(selected_piece, self.selection, pos, self.board):
            self.board.move_piece(self.selection, pos)
        self.selection = None

    def wait(self, ms: int) -> None:
        """Advance the game clock by *ms* milliseconds."""
        self._clock_ms += ms

    # ------------------------------------------------------------------
    # Read-only accessors
    # ------------------------------------------------------------------

    @property
    def clock_ms(self) -> int:
        """Current game-clock value in milliseconds."""
        return self._clock_ms

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_friendly(piece_a: str | None, piece_b: str | None) -> bool:
        """Return True if both pieces belong to the same colour."""
        if piece_a is None or piece_b is None:
            return False
        return piece_a[0] == piece_b[0]
