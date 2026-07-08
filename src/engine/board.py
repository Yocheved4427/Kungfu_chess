from __future__ import annotations

from abc import ABC, abstractmethod
from typing import FrozenSet, List

from src.core.models import Color, Position

# ---------------------------------------------------------------------------
# Kung Fu Chess – Board representation, parsing, and validation
# ---------------------------------------------------------------------------
# Three distinct responsibilities, each in its own class:
#
#   AbstractBoard / TextBoard  – board storage and mutation.
#   BoardParser                – raw text lines → AbstractBoard.
#   BoardValidator             – structural integrity checks on parsed rows.
#
# All consumers depend on AbstractBoard only (Dependency Inversion), so the
# concrete storage format can be swapped without touching any other layer.
# ---------------------------------------------------------------------------


# ===========================================================================
# Board abstraction
# ===========================================================================

class AbstractBoard(ABC):
    """Stable interface for a chess board.

    All business logic depends on this interface, never on TextBoard directly.
    """

    @abstractmethod
    def get_rows(self) -> List[str]:
        """Return the board as an ordered list of row strings (top → bottom)."""

    @property
    @abstractmethod
    def num_rows(self) -> int:
        """Total number of ranks."""

    @property
    @abstractmethod
    def num_cols(self) -> int:
        """Total number of files (columns)."""

    @abstractmethod
    def render(self) -> str:
        """Canonical text representation; rows separated by newlines."""

    @abstractmethod
    def get_piece_at(self, pos: Position) -> str | None:
        """Return the token at *pos* (e.g. ``"wK"``, ``"."``) or ``None`` if OOB."""

    @abstractmethod
    def move_piece(self, from_pos: Position, to_pos: Position) -> None:
        """Move the piece at *from_pos* to *to_pos*, leaving *from_pos* empty.

        If *to_pos* contains an enemy piece it is overwritten (capture).
        Callers are responsible for ensuring legality before calling this method;
        no validation is performed here.
        """

    def get_color_at(self, pos: Position) -> Color | None:
        """Return the Color at *pos*, or ``None`` for empty / out-of-bounds."""
        piece = self.get_piece_at(pos)
        if piece is None or piece == ".":
            return None
        if piece[0] == Color.WHITE.value:
            return Color.WHITE
        if piece[0] == Color.BLACK.value:
            return Color.BLACK
        return None


# ===========================================================================
# Concrete board
# ===========================================================================

class TextBoard(AbstractBoard):
    """Board stored as a list of space-separated token strings.

    Token format::

        wK  wQ  wR  wB  wN  wP  – white pieces
        bK  bQ  bR  bB  bN  bP  – black pieces
        .                        – empty square

    Example row: ``"wR wN wB wQ wK wB wN wR"``
    """

    def __init__(self, rows: List[str]) -> None:
        self._rows: List[str] = list(rows)   # defensive copy

    def get_rows(self) -> List[str]:
        return list(self._rows)

    @property
    def num_rows(self) -> int:
        return len(self._rows)

    @property
    def num_cols(self) -> int:
        return len(self._rows[0].split()) if self._rows else 0

    def render(self) -> str:
        return "\n".join(self._rows)

    def get_piece_at(self, pos: Position) -> str | None:
        if pos.row < 0 or pos.row >= self.num_rows:
            return None
        tokens = self._rows[pos.row].split()
        if pos.col < 0 or pos.col >= len(tokens):
            return None
        return tokens[pos.col]

    def move_piece(self, from_pos: Position, to_pos: Position) -> None:
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


# ===========================================================================
# Board parsing
# ===========================================================================

class BoardParser:
    """Converts raw text lines into an ``AbstractBoard`` instance.

    Single responsibility: strip line endings and discard trailing blank lines.
    """

    def parse(self, lines: List[str]) -> AbstractBoard:
        rows: List[str] = [line.rstrip("\r\n") for line in lines]
        while rows and rows[-1] == "":
            rows.pop()
        return TextBoard(rows)


# ===========================================================================
# Board validation
# ===========================================================================

class BoardValidationError(ValueError):
    """Raised when a board fails structural or token validation."""


class BoardValidator:
    """Asserts that board rows contain only known tokens and uniform width.

    Injected with ``valid_chars`` so this class stays rule-agnostic; all
    magic values live in ``src.core.config``.
    """

    def __init__(self, valid_chars: FrozenSet[str]) -> None:
        self._valid_chars = valid_chars

    def validate(self, rows: List[str]) -> None:
        if not rows:
            raise BoardValidationError("EMPTY_BOARD")
        expected_width = len(rows[0].split())
        for row in rows:
            for token in row.split():
                if token not in self._valid_chars:
                    raise BoardValidationError("UNKNOWN_TOKEN")
            if len(row.split()) != expected_width:
                raise BoardValidationError("ROW_WIDTH_MISMATCH")
