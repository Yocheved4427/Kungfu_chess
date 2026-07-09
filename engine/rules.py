from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from core.models import Position

if TYPE_CHECKING:
    from engine.board import AbstractBoard

# ---------------------------------------------------------------------------
# Kung Fu Chess – Movement Rules  (Strategy Pattern / OCP)
# ---------------------------------------------------------------------------
# Hierarchy:
#   MovementRule (ABC)
#     ├── OrthogonalRule  – horizontal / vertical, any distance  (sliding)
#     ├── DiagonalRule    – diagonal, any distance               (sliding)
#     ├── KnightRule      – L-shape, two squares                 (jumping)
#     ├── KingRule        – one step any direction               (non-sliding)
#     ├── PawnRule        – direction & dest-aware               (non-sliding)
#     └── _CompositeRule  – union of rules (internal; used for Queen)
#
#   MoveValidator
#     * Registry: piece-type char → MovementRule instance.
#     * Context check (shape + dest) → friendly-fire → path (sliding only).
# ---------------------------------------------------------------------------


# ===========================================================================
# Abstract interface
# ===========================================================================

class MovementRule(ABC):
    """Abstract Strategy for validating move geometry.

    Two-level interface:
    * ``is_valid_shape``        – pure geometry, no board state.
    * ``is_valid_with_context`` – full legality including destination content.
      Default delegates to ``is_valid_shape``; override for pieces (e.g. Pawn)
      whose legality depends on whether the target square is empty or occupied.
    """

    @abstractmethod
    def is_valid_shape(self, from_pos: Position, to_pos: Position) -> bool:
        """Return True iff the displacement is geometrically legal (board-agnostic)."""

    @property
    @abstractmethod
    def is_sliding(self) -> bool:
        """True iff this piece glides along a ray and can be blocked."""

    def is_valid_with_context(
        self,
        piece: str,
        from_pos: Position,
        to_pos: Position,
        dest_piece: str | None,
    ) -> bool:
        """Return True iff the move is legal given the content of the destination.

        Default ignores ``dest_piece`` and delegates to ``is_valid_shape``.
        Override for destination-sensitive pieces such as the Pawn.
        """
        return self.is_valid_shape(from_pos, to_pos)


# ===========================================================================
# Concrete rules
# ===========================================================================

class OrthogonalRule(MovementRule):
    """Horizontal or vertical movement, any distance.  Used by Rook."""

    @property
    def is_sliding(self) -> bool:
        return True

    def is_valid_shape(self, from_pos: Position, to_pos: Position) -> bool:
        dr = to_pos.row - from_pos.row
        dc = to_pos.col - from_pos.col
        return (dr == 0) != (dc == 0)   # exactly one axis moves


class DiagonalRule(MovementRule):
    """Diagonal movement, any distance.  Used by Bishop."""

    @property
    def is_sliding(self) -> bool:
        return True

    def is_valid_shape(self, from_pos: Position, to_pos: Position) -> bool:
        dr = abs(to_pos.row - from_pos.row)
        dc = abs(to_pos.col - from_pos.col)
        return dr == dc and dr > 0


class KnightRule(MovementRule):
    """L-shaped Knight movement.  Jumps over pieces — never blocked."""

    @property
    def is_sliding(self) -> bool:
        return False

    def is_valid_shape(self, from_pos: Position, to_pos: Position) -> bool:
        dr = abs(to_pos.row - from_pos.row)
        dc = abs(to_pos.col - from_pos.col)
        return (dr, dc) in {(1, 2), (2, 1)}


class _CompositeRule(MovementRule):
    """Accepts a move valid under *any* of the composed rules.

    ``is_sliding`` is True if at least one component is sliding.
    Internal helper — Queen = _CompositeRule(OrthogonalRule(), DiagonalRule()).
    """

    def __init__(self, *rules: MovementRule) -> None:
        self._rules: tuple[MovementRule, ...] = rules

    @property
    def is_sliding(self) -> bool:
        return any(r.is_sliding for r in self._rules)

    def is_valid_shape(self, from_pos: Position, to_pos: Position) -> bool:
        return any(r.is_valid_shape(from_pos, to_pos) for r in self._rules)


class KingRule(MovementRule):
    """One step in any direction (Chebyshev distance = 1).

    Shares the Queen's direction set but is capped to a single step.
    Never sliding — no intermediate squares exist for a 1-step move.
    """

    _QUEEN_SHAPE: MovementRule = _CompositeRule(OrthogonalRule(), DiagonalRule())

    @property
    def is_sliding(self) -> bool:
        return False

    def is_valid_shape(self, from_pos: Position, to_pos: Position) -> bool:
        dr = abs(to_pos.row - from_pos.row)
        dc = abs(to_pos.col - from_pos.col)
        return (
            max(dr, dc) == 1
            and self._QUEEN_SHAPE.is_valid_shape(from_pos, to_pos)
        )


class PawnRule(MovementRule):
    """Pawn movement — a single class covers both colours.

    Direction is derived from the colour prefix of the piece token:
      ``'w'`` (white) → direction = -1  (decreasing row = moving up)
      ``'b'`` (black) → direction = +1  (increasing row = moving down)

    Two legal sub-moves (non-sliding, no double-step):
      Forward move   ``d_row == direction, d_col == 0``
                     → ONLY when destination is strictly empty (``"."``).
      Diagonal capture ``d_row == direction, abs(d_col) == 1``
                     → ONLY when destination is occupied by an enemy piece
                       (friendly-fire guard in MoveValidator handles colour).
    """

    @property
    def is_sliding(self) -> bool:
        return False

    def is_valid_shape(self, from_pos: Position, to_pos: Position) -> bool:
        """Loose geometry check (board-agnostic): one step forward or diagonal."""
        d_row = abs(to_pos.row - from_pos.row)
        d_col = abs(to_pos.col - from_pos.col)
        return d_row == 1 and d_col in (0, 1)

    def is_valid_with_context(
        self,
        piece: str,
        from_pos: Position,
        to_pos: Position,
        dest_piece: str | None,
    ) -> bool:
        """Full pawn legality: direction + destination-content checks."""
        direction: int = -1 if piece[0] == "w" else 1
        d_row: int = to_pos.row - from_pos.row
        d_col: int = to_pos.col - from_pos.col

        if d_row != direction:
            return False
        if d_col == 0:
            return dest_piece == "."
        if abs(d_col) == 1:
            return dest_piece is not None and dest_piece != "."
        return False


# ===========================================================================
# Default registry
# ===========================================================================

_QUEEN_RULE: MovementRule = _CompositeRule(OrthogonalRule(), DiagonalRule())

_DEFAULT_RULES: dict[str, MovementRule] = {
    "R": OrthogonalRule(),
    "B": DiagonalRule(),
    "Q": _QUEEN_RULE,
    "N": KnightRule(),
    "K": KingRule(),
    "P": PawnRule(),   # direction derived from colour prefix at validation time
}


# ===========================================================================
# MoveValidator
# ===========================================================================

class MoveValidator:
    """Registry-based move validator.

    Maps piece-type characters (``"K"``, ``"R"``, …) to ``MovementRule``
    instances.  New piece behaviour requires only calling ``register()`` —
    no changes to this class or the engine (OCP extension point).

    The engine calls ``is_valid()`` and has zero knowledge of chess rules.
    """

    def __init__(self, rules: dict[str, MovementRule] | None = None) -> None:
        self._rules: dict[str, MovementRule] = dict(
            _DEFAULT_RULES if rules is None else rules
        )

    def register(self, piece_type: str, rule: MovementRule) -> None:
        """Register or replace the ``MovementRule`` for *piece_type*."""
        self._rules[piece_type] = rule

    def is_valid(
        self,
        piece: str,
        from_pos: Position,
        to_pos: Position,
        board: AbstractBoard,
    ) -> bool:
        """Return True iff *piece* may legally move from *from_pos* to *to_pos*."""
        if from_pos == to_pos:
            return False
        piece_type = piece[1]          # "wK" → "K",  "bR" → "R"
        rule = self._rules.get(piece_type)
        if rule is None:
            return False
        dest = board.get_piece_at(to_pos)
        # Shape + destination-context check (handles Pawn forward vs. capture).
        if not rule.is_valid_with_context(piece, from_pos, to_pos, dest):
            return False
        # Friendly fire: cannot land on a square occupied by own colour.
        if dest is not None and dest != "." and dest[0] == piece[0]:
            return False
        # Sliding pieces must have an unobstructed path.
        if rule.is_sliding:
            return self._path_clear(board, from_pos, to_pos)
        return True

    @staticmethod
    def _path_clear(
        board: AbstractBoard, from_pos: Position, to_pos: Position
    ) -> bool:
        """Return True iff every square strictly between from and to is empty."""
        dr = to_pos.row - from_pos.row
        dc = to_pos.col - from_pos.col
        steps = max(abs(dr), abs(dc))
        step_r = dr // steps
        step_c = dc // steps
        r, c = from_pos.row + step_r, from_pos.col + step_c
        while (r, c) != (to_pos.row, to_pos.col):
            if board.get_piece_at(Position(r, c)) != ".":
                return False
            r += step_r
            c += step_c
        return True