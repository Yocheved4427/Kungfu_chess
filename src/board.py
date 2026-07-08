from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from src.models import Color, Position


# ---------------------------------------------------------------------------
# Kung Fu Chess – Board representation
# ---------------------------------------------------------------------------
# AbstractBoard is the stable contract used by every other layer.
# Swap TextBoard for a bitboard, binary, or network representation at any
# time without touching the parser, validator, or I/O handler.
# ---------------------------------------------------------------------------


class AbstractBoard(ABC):
    """
    Language-agnostic interface for a chess board.

    All business logic depends on this interface, never on a concrete class,
    so the internal storage format can be replaced freely (Open/Closed).
    """

    @abstractmethod
    def get_rows(self) -> List[str]:
        """Return the board as an ordered list of row strings (top → bottom)."""

    @property
    @abstractmethod
    def num_rows(self) -> int:
        """Total number of ranks on the board."""

    @property
    @abstractmethod
    def num_cols(self) -> int:
        """Total number of files (columns) on the board."""

    @abstractmethod
    def render(self) -> str:
        """
        Produce the canonical text representation of the board.
        Rows are separated by newline characters; no trailing newline is added
        by this method (the caller controls line termination).
        """

    @abstractmethod
    def get_piece_at(self, pos: Position) -> str | None:
        """
        Return the token at *pos* (e.g. ``"wK"``, ``"."``) or ``None`` if
        the position is out of bounds.
        """

    @abstractmethod
    def move_piece(self, from_pos: Position, to_pos: Position) -> None:
        """Move the piece at *from_pos* to *to_pos*, leaving *from_pos* empty."""

    def get_color_at(self, pos: Position) -> Color | None:
        """
        Return the Color of the piece at *pos*, or ``None`` for an empty
        square or an out-of-bounds position.

        Concrete implementation shared by all subclasses; depends only on
        ``get_piece_at`` which is abstract.
        """
        piece = self.get_piece_at(pos)
        if piece is None or piece == ".":
            return None
        if piece[0] == Color.WHITE.value:
            return Color.WHITE
        if piece[0] == Color.BLACK.value:
            return Color.BLACK
        return None


class TextBoard(AbstractBoard):
    """
    Concrete board that stores each rank as a space-separated token string.

    Token format:
      ``wK``  ``wQ``  ``wR``  ``wB``  ``wN``  ``wP``  – white pieces
      ``bK``  ``bQ``  ``bR``  ``bB``  ``bN``  ``bP``  – black pieces
      ``.``                                            – empty square

    Example row: ``"wR wN wB wQ wK wB wN wR"``
    """

    def __init__(self, rows: List[str]) -> None:
        # Defensive copy so the caller cannot mutate internal state.
        self._rows: List[str] = list(rows)

    # ------------------------------------------------------------------
    # AbstractBoard implementation
    # ------------------------------------------------------------------

    def get_rows(self) -> List[str]:
        return list(self._rows)   # return a copy for encapsulation

    @property
    def num_rows(self) -> int:
        return len(self._rows)

    @property
    def num_cols(self) -> int:
        """Number of token-columns inferred from the first row."""
        return len(self._rows[0].split()) if self._rows else 0

    def render(self) -> str:
        return "\n".join(self._rows)

    def get_piece_at(self, pos: Position) -> str | None:
        """Return the token at *pos*, or ``None`` if out of bounds."""
        if pos.row < 0 or pos.row >= self.num_rows:
            return None
        tokens = self._rows[pos.row].split()
        if pos.col < 0 or pos.col >= len(tokens):
            return None
        return tokens[pos.col]

    def move_piece(self, from_pos: Position, to_pos: Position) -> None:
        """Moves a piece from one position to another on the board."""
        if from_pos == to_pos:
            return

        from_tokens = self._rows[from_pos.row].split()
        piece = from_tokens[from_pos.col]

        if from_pos.row == to_pos.row:
            from_tokens[from_pos.col] = "."
            from_tokens[to_pos.col] = piece
            self._rows[from_pos.row] = " ".join(from_tokens)
        else:
            to_tokens = self._rows[to_pos.row].split()
            from_tokens[from_pos.col] = "."
            to_tokens[to_pos.col] = piece
            self._rows[from_pos.row] = " ".join(from_tokens)
            self._rows[to_pos.row] = " ".join(to_tokens)
