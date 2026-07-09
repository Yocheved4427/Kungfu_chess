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

    def requires_path_check(self, from_pos: Position, to_pos: Position) -> bool:
        """Return True iff every square strictly between *from_pos* and
        *to_pos* must be empty for this exact move.

        Default mirrors ``is_sliding`` — always for sliding pieces, never
        otherwise. Override for a piece whose blocking behaviour depends
        on the specific move rather than being fixed (e.g. Pawn: blockable
        on its two-step advance, but not on its normal one-step moves).
        """
        return self.is_sliding

    def is_valid_with_board(
        self,
        piece: str,
        from_pos: Position,
        to_pos: Position,
        board: AbstractBoard,
    ) -> bool:
        """Optional third-tier check with full board access, for legality
        that depends on more than shape + destination content — e.g. a
        Pawn's double-step is only legal from its colour's start row,
        which requires knowing the board's dimensions.

        Default: no extra restriction (True).
        """
        return True


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

    Three legal sub-moves (non-sliding, except the two-step advance):
      Forward move     ``d_row == direction, d_col == 0``
                       → ONLY when destination is strictly empty (``"."``).
      Two-step advance ``d_row == 2*direction, d_col == 0``
                       → ONLY from the colour's start row (checked via
                         ``is_valid_with_board``, which needs the board's
                         height), destination strictly empty, and the
                         intermediate square clear (``requires_path_check``
                         routes this through MoveValidator's normal
                         ``_path_clear``, same as a sliding piece).
      Diagonal capture ``d_row == direction, abs(d_col) == 1``
                       → ONLY when destination is occupied by an enemy piece
                         (friendly-fire guard in MoveValidator handles colour).

    Promotion (a Pawn reaching the back rank becomes a Queen) is a board
    mutation applied by ``GameEngine`` after the move resolves — it isn't
    a legality concern and has no bearing on this class.
    """

    @property
    def is_sliding(self) -> bool:
        return False

    def is_valid_shape(self, from_pos: Position, to_pos: Position) -> bool:
        """Loose geometry check (board-agnostic): one step forward/diagonal,
        or two straight. Direction, start-row, and path are enforced by
        ``is_valid_with_context`` / ``is_valid_with_board``."""
        d_row = abs(to_pos.row - from_pos.row)
        d_col = abs(to_pos.col - from_pos.col)
        if d_col == 0:
            return d_row in (1, 2)
        return d_row == 1 and d_col == 1

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

        if d_col == 0:
            if d_row not in (direction, 2 * direction):
                return False
            return dest_piece == "."
        if d_row == direction and abs(d_col) == 1:
            return dest_piece is not None and dest_piece != "."
        return False

    def requires_path_check(self, from_pos: Position, to_pos: Position) -> bool:
        """Only the two-step advance can be blocked mid-flight."""
        return abs(to_pos.row - from_pos.row) == 2

    def is_valid_with_board(
        self,
        piece: str,
        from_pos: Position,
        to_pos: Position,
        board: AbstractBoard,
    ) -> bool:
        """The two-step advance is only legal from the colour's start row.

        A colour's start row is the board edge it advances *away* from:
        White's is the last row (``num_rows - 1``); Black's is row 0 —
        the mirror image. One-/zero-step moves are unrestricted here.
        """
        if abs(to_pos.row - from_pos.row) != 2:
            return True
        start_row = board.num_rows - 1 if piece[0] == "w" else 0
        return from_pos.row == start_row


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
        # Sliding pieces (and pieces like Pawn whose blocking is move-
        # specific, e.g. its two-step advance) must have a clear path.
        if rule.requires_path_check(from_pos, to_pos) and not self._path_clear(
            board, from_pos, to_pos
        ):
            return False
        # Final board-aware check (e.g. Pawn's two-step start-row rule).
        return rule.is_valid_with_board(piece, from_pos, to_pos, board)

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