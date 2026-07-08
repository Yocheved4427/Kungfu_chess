from __future__ import annotations

from src.board import AbstractBoard
from src.models import Position


# ---------------------------------------------------------------------------
# Kung Fu Chess – Game Engine (Iteration 2)
# ---------------------------------------------------------------------------
# Single responsibility: encapsulate the game clock, the selection state
# machine, and the pixel-to-cell coordinate conversion.
#
# The engine is intentionally board-agnostic (depends on AbstractBoard only)
# and has no I/O awareness.
# ---------------------------------------------------------------------------


class GameEngine:
    """
    Core game state machine for Kung Fu Chess.

    Responsibilities
    ----------------
    * Convert pixel coordinates to board cells (``handle_click``).
    * Manage the single-piece selection state.
    * Apply moves directly to the board via ``board.move_piece``.
    * Advance the game clock (``wait``).
    """

    def __init__(self, board: AbstractBoard, cell_size: int = 100) -> None:
        self.board: AbstractBoard = board
        self.selection: Position | None = None
        self._clock_ms: int = 0
        self._cell_size: int = cell_size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle_click(self, x: int, y: int) -> None:
        """
        Process a pixel-coordinate click.

        Coordinate conversion
        ---------------------
        ``col = x // 100``,  ``row = y // 100``

        State-machine rules
        -------------------
        * Out-of-bounds click → ignored.
        * No selection, click on empty square → ignored.
        * No selection, click on piece → piece is selected.
        * Selection exists, click on friendly piece → selection replaced.
        * Selection exists, click on empty or enemy cell → move applied,
          selection cleared.
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
        else:
            selected_piece = self.board.get_piece_at(self.selection)
            if clicked_piece != "." and self._is_friendly(selected_piece, clicked_piece):
                self.selection = pos
            else:
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
        """Return True if both pieces belong to the same color."""
        if piece_a is None or piece_b is None:
            return False
        return piece_a[0] == piece_b[0]

