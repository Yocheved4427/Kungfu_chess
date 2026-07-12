from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from core.models import Color, Position

# ---------------------------------------------------------------------------
# Kung Fu Chess – Board representation
# ---------------------------------------------------------------------------
# AbstractBoard / TextBoard  – pure logical board state: which piece (if
# any) occupies which (row, col) cell, and mutating that. Nothing here
# knows about pixels, screen coordinates, mouse clicks, rendering/display,
# or animation — those are separate concerns, kept in separate components:
#   * Pixel <-> cell translation and click/jump handling: engine.game.GameEngine.
#   * Turning board state into a displayable form: engine.board_renderer.
#
# BoardParser lives in engine.board_parser.
# BoardValidator lives in engine.board_validator.
# All consumers depend on AbstractBoard only (Dependency Inversion).
#
# Mutation ownership: move_piece() / set_piece_at() exist here so
# GameEngine — the single service layer that owns game state — has
# somewhere to apply an approved move. No other component should call
# them: validators/rule engines (engine.rules, engine.rule_engine) only
# ever read a board to decide legality; they never mutate one.
# ---------------------------------------------------------------------------


# ===========================================================================
# Board abstraction
# ===========================================================================

class AbstractBoard(ABC):
    """Stable interface for a chess board's logical state.

    All business logic depends on this interface, never on TextBoard
    directly. Deliberately minimal: rows/columns and piece tokens only —
    no pixels, no rendering, no input handling.
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
    def get_piece_at(self, pos: Position) -> str | None:
        """Return the token at *pos* (e.g. ``"wK"``, ``"."``) or ``None`` if OOB."""

    @abstractmethod
    def move_piece(self, from_pos: Position, to_pos: Position) -> None:
        """Move the piece at *from_pos* to *to_pos*, leaving *from_pos* empty."""

    @abstractmethod
    def set_piece_at(self, pos: Position, piece: str) -> None:
        """Overwrite the token at *pos* with *piece* (e.g. for promotion).

        Unlike ``move_piece`` this touches only a single cell — no origin
        is emptied.
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

    def contains(self, pos: Position) -> bool:
        """Return True iff *pos* is a real cell on this board.

        The single shared bounds check — callers (ClickController,
        GameEngine.handle_jump, RuleEngine, ...) use this instead of each
        re-deriving ``0 <= row < num_rows and 0 <= col < num_cols``.
        """
        return 0 <= pos.row < self.num_rows and 0 <= pos.col < self.num_cols


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

    def set_piece_at(self, pos: Position, piece: str) -> None:
        tokens = self._rows[pos.row].split()
        tokens[pos.col] = piece
        self._rows[pos.row] = " ".join(tokens)

