from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import TYPE_CHECKING

from core.models import Position, same_color
from engine.geometry import (
    is_diagonal,
    is_king_step,
    is_knight_shape,
    is_orthogonal,
    path_clear,
    pawn_direction,
    pawn_start_row,
)

if TYPE_CHECKING:
    from engine.board import AbstractBoard

# ---------------------------------------------------------------------------
# Kung Fu Chess – Rule Engine  (Strategy Pattern / OCP)
# ---------------------------------------------------------------------------
# A second, independent legality checker alongside engine.rules — same
# underlying chess semantics (including the Pawn's two-step advance and
# path-blocking), but shaped differently on purpose:
#
#   * One concrete class per piece TYPE (RookRule, BishopRule, ...) rather
#     than per movement SHAPE (OrthogonalRule/DiagonalRule composed for
#     Queen) — a piece's identity, not just its geometry, owns its rule.
#   * validate_move() never returns a bare bool. It returns a MoveResult
#     enum member so a caller can tell WHY a move is illegal — outside
#     the board, no piece there, wrong shape, blocked path, landing on a
#     friendly — not just THAT it is.
#
# Hierarchy:
#   IPieceRule (ABC)
#     ├── RookRule    – horizontal / vertical, any distance   (blockable)
#     ├── BishopRule  – diagonal, any distance                (blockable)
#     ├── QueenRule   – rook + bishop shapes combined          (blockable)
#     ├── KnightRule  – L-shape, two squares                   (jumps)
#     ├── KingRule    – one step, any direction                (never blocked)
#     └── PawnRule    – direction/dest-aware; two-step from the colour's
#                        start row is the only blockable Pawn move
#
#   RuleEngine
#     * Registry: piece-type char -> IPieceRule instance (register() is
#       the OCP extension point, same idea as MoveValidator.register()).
#     * validate_move() checks, in order: bounds, same-position, empty
#       source, known piece type, pattern (delegated to the IPieceRule),
#       friendly-fire, blocked path -> MoveResult.
#
# This module doesn't depend on engine.rules or GameEngine (no import
# cycle) — but GameEngine.try_move is now backed by it: RuleEngine only
# ever READS the board to decide legality, and GameEngine is the sole
# component that applies the resulting mutation. The original real-time
# pipeline (handle_click -> ClickController -> attempt_move -> tick) is
# untouched and still runs on MoveValidator/engine.rules — see
# GameEngine.try_move's docstring for how the two pathways differ.
# ---------------------------------------------------------------------------


# ===========================================================================
# Result type
# ===========================================================================

class MoveResult(Enum):
    """Outcome of ``RuleEngine.validate_move`` — deliberately never a bool.

    ``OK`` is the only success value; every other member names a
    specific reason the move was rejected.

    ``GAME_OVER`` is never produced by ``validate_move`` itself — a
    finished game is GameEngine-level state RuleEngine has no notion of.
    It exists so ``GameEngine.try_move`` (the only other producer of
    this enum) can still return a single, complete ``MoveResult``
    instead of inventing a second result type just for that one case.
    """
    OK = auto()
    OUTSIDE_BOARD = auto()
    SAME_POSITION = auto()
    EMPTY_SOURCE = auto()
    UNKNOWN_PIECE_TYPE = auto()
    ILLEGAL_PATTERN = auto()
    FRIENDLY_FIRE = auto()
    BLOCKED_PATH = auto()
    GAME_OVER = auto()

    @property
    def is_ok(self) -> bool:
        """Convenience predicate — the only ergonomic bool this module
        offers; ``validate_move``/``try_move`` themselves always return
        the full enum."""
        return self is MoveResult.OK


# ===========================================================================
# Abstract interface
# ===========================================================================

class IPieceRule(ABC):
    """Strategy interface: one implementation per piece type.

    Two-method contract:
    * ``is_legal_move``      – does this piece's pattern (shape + colour
      direction + destination content, where relevant) allow this move?
      Callers guarantee ``from_pos`` holds a piece and both cells are
      on the board before calling this — a rule never has to check that.
    * ``requires_path_check`` – must every square strictly between
      ``from_pos``/``to_pos`` be empty for this specific move? Default
      False (jumping / fixed-distance pieces); sliding pieces override
      to always return True, and Pawn overrides to return True only for
      its two-step advance.
    """

    @abstractmethod
    def is_legal_move(
        self, piece: str, from_pos: Position, to_pos: Position, board: AbstractBoard
    ) -> bool:
        """Return True iff *piece* may travel from *from_pos* to *to_pos*,
        ignoring friendly-fire and path-blocking (RuleEngine handles
        those generically for every piece type)."""

    def requires_path_check(self, from_pos: Position, to_pos: Position) -> bool:
        return False


# ===========================================================================
# Concrete piece rules
# ===========================================================================

class RookRule(IPieceRule):
    """Horizontal or vertical movement, any distance. Blockable."""

    def is_legal_move(self, piece, from_pos, to_pos, board) -> bool:
        return is_orthogonal(from_pos, to_pos)

    def requires_path_check(self, from_pos, to_pos) -> bool:
        return True


class BishopRule(IPieceRule):
    """Diagonal movement, any distance. Blockable."""

    def is_legal_move(self, piece, from_pos, to_pos, board) -> bool:
        return is_diagonal(from_pos, to_pos)

    def requires_path_check(self, from_pos, to_pos) -> bool:
        return True


class QueenRule(IPieceRule):
    """Rook + Bishop shapes combined, any distance. Blockable."""

    def is_legal_move(self, piece, from_pos, to_pos, board) -> bool:
        return is_orthogonal(from_pos, to_pos) or is_diagonal(from_pos, to_pos)

    def requires_path_check(self, from_pos, to_pos) -> bool:
        return True


class KnightRule(IPieceRule):
    """L-shaped movement. Jumps over pieces — never blockable."""

    def is_legal_move(self, piece, from_pos, to_pos, board) -> bool:
        return is_knight_shape(from_pos, to_pos)


class KingRule(IPieceRule):
    """One step in any direction. Never blockable (no square in between)."""

    def is_legal_move(self, piece, from_pos, to_pos, board) -> bool:
        return is_king_step(from_pos, to_pos)


class PawnRule(IPieceRule):
    """Pawn movement — one class covers both colours.

    Direction is derived from the colour prefix of the piece token:
      ``'w'`` (white) -> direction = -1 (decreasing row = moving up)
      ``'b'`` (black) -> direction = +1 (increasing row = moving down)

    Legal sub-moves:
      Forward move     ``d_row == direction, d_col == 0``
                        -> destination must be strictly empty.
      Two-step advance ``d_row == 2*direction, d_col == 0``
                        -> ONLY from the colour's start row (one row in
                        front of the back rank it advances away from:
                        ``num_rows - 2`` for White, ``1`` for Black),
                        destination strictly empty. This is the only
                        Pawn move that can be blocked mid-flight — see
                        ``requires_path_check``.
      Diagonal capture ``d_row == direction, abs(d_col) == 1``
                        -> ONLY onto a square occupied by an enemy piece
                        (friendly-fire is still cross-checked generically
                        by RuleEngine, same as every other piece).
    """

    def is_legal_move(self, piece, from_pos, to_pos, board) -> bool:
        direction = pawn_direction(piece)
        d_row = to_pos.row - from_pos.row
        d_col = to_pos.col - from_pos.col
        dest = board.get_piece_at(to_pos)

        if d_col == 0:
            if d_row == direction:
                return dest == "."
            if d_row == 2 * direction:
                if dest != ".":
                    return False
                return from_pos.row == pawn_start_row(piece, board.num_rows)
            return False

        if d_row == direction and abs(d_col) == 1:
            return dest is not None and dest != "."
        return False

    def requires_path_check(self, from_pos, to_pos) -> bool:
        return abs(to_pos.row - from_pos.row) == 2


# ===========================================================================
# Default registry
# ===========================================================================

_DEFAULT_RULES: dict[str, IPieceRule] = {
    "R": RookRule(),
    "B": BishopRule(),
    "Q": QueenRule(),
    "N": KnightRule(),
    "K": KingRule(),
    "P": PawnRule(),
}


# ===========================================================================
# RuleEngine
# ===========================================================================

class RuleEngine:
    """Registry-based move-legality checker.

    Maps piece-type characters (``"K"``, ``"R"``, ...) to ``IPieceRule``
    instances. New piece behaviour requires only calling ``register()`` —
    no changes to this class (OCP extension point).

    ``validate_move`` is the single entry point and never returns a bare
    bool — always a ``MoveResult`` naming exactly why a move is or isn't
    legal.
    """

    def __init__(self, rules: dict[str, IPieceRule] | None = None) -> None:
        self._rules: dict[str, IPieceRule] = dict(
            _DEFAULT_RULES if rules is None else rules
        )

    def register(self, piece_type: str, rule: IPieceRule) -> None:
        """Register or replace the ``IPieceRule`` for *piece_type*."""
        self._rules[piece_type] = rule

    def validate_move(
        self,
        piece: str,
        from_pos: Position,
        to_pos: Position,
        board: AbstractBoard,
    ) -> MoveResult:
        """Classify a proposed move from *from_pos* to *to_pos*.

        *piece* is the mover's expected token (e.g. ``"wR"``) — used to
        look up its rule and its colour; the actual occupant of
        *from_pos* is read fresh from *board* for the emptiness check.
        """
        if not (board.contains(from_pos) and board.contains(to_pos)):
            return MoveResult.OUTSIDE_BOARD

        if from_pos == to_pos:
            return MoveResult.SAME_POSITION

        source = board.get_piece_at(from_pos)
        if source is None or source == ".":
            return MoveResult.EMPTY_SOURCE

        rule = self._rules.get(piece[1])
        if rule is None:
            return MoveResult.UNKNOWN_PIECE_TYPE

        if not rule.is_legal_move(piece, from_pos, to_pos, board):
            return MoveResult.ILLEGAL_PATTERN

        dest = board.get_piece_at(to_pos)
        # same_color(".", piece) is always False, so no extra guard is needed.
        if same_color(dest, piece):
            return MoveResult.FRIENDLY_FIRE

        if rule.requires_path_check(from_pos, to_pos) and not path_clear(
            board, from_pos, to_pos
        ):
            return MoveResult.BLOCKED_PATH

        return MoveResult.OK
