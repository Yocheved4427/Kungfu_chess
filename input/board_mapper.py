from __future__ import annotations

from core.models import Position

# ---------------------------------------------------------------------------
# Kung Fu Chess – Coordinate Adapter
# ---------------------------------------------------------------------------
# BoardMapper is the single place in the codebase that translates between
# screen/pixel coordinates and logical (row, col) board coordinates.
# Board itself knows nothing about pixels (see engine/board.py); GameEngine
# knows nothing about the arithmetic either — it just calls this. No other
# component should do `x // cell_size` (or the inverse) directly.
# ---------------------------------------------------------------------------


class BoardMapper:
    """Coordinate adapter between pixel space and logical board cells.

    Cells are square, ``cell_size`` pixels on a side. Construct directly
    with a known cell size, or via ``from_board_pixels`` to derive that
    size from the board's total pixel dimensions and its grid shape.
    """

    def __init__(self, cell_size: int) -> None:
        if cell_size <= 0:
            raise ValueError(f"cell_size must be positive, got {cell_size}")
        self._cell_size = cell_size

    @classmethod
    def from_board_pixels(
        cls,
        board_width_px: int,
        board_height_px: int,
        num_cols: int,
        num_rows: int,
    ) -> "BoardMapper":
        """Derive a uniform square cell size from the board's total pixel
        dimensions and its grid shape.

        Takes the smaller of the two per-axis sizes so cells stay square
        even if ``board_width_px`` / ``board_height_px`` aren't perfectly
        proportional to ``num_cols`` / ``num_rows``.
        """
        if num_cols <= 0 or num_rows <= 0:
            raise ValueError("num_cols and num_rows must be positive")
        cell_size = min(board_width_px // num_cols, board_height_px // num_rows)
        return cls(cell_size)

    @property
    def cell_size(self) -> int:
        return self._cell_size

    def pixel_to_cell(self, x: int, y: int) -> Position:
        """Return the (row, col) cell containing pixel (x, y)."""
        return Position(row=y // self._cell_size, col=x // self._cell_size)

    def cell_to_pixel(self, row: int, col: int) -> tuple[int, int]:
        """Return the (x, y) pixel coordinate of cell (row, col)'s
        top-left corner — the inverse of ``pixel_to_cell``."""
        return (col * self._cell_size, row * self._cell_size)
