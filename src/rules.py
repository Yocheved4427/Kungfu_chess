from __future__ import annotations

from abc import ABC, abstractmethod

from src.board import AbstractBoard
from src.models import Position

# ---------------------------------------------------------------------------
# Kung Fu Chess – Movement Rules (Iteration 3)
# ---------------------------------------------------------------------------
# Open/Closed Principle: the validator is open for extension (register any
# new piece type or replace an existing rule at runtime) and closed for
# modification (no existing code needs to change).
#
# Design
# ------
#   MovementRule (ABC)
#     ├── OrthogonalMove   – horizontal / vertical, any distance  (sliding)
#     ├── DiagonalMove     – diagonal, any distance               (sliding)
#     ├── LShapeMove       – L-shape (Knight)                     (jumping)
#     ├── CompositeMove    – union of several rules
#     └── OneStepMove      – wraps any rule, caps to 1 step       (never sliding)
#
#   MoveValidator
#     * Holds a registry: piece-type char → MovementRule instance.
#     * Performs shape check (rule) then path check (if sliding).
#     * The Engine calls is_valid() and knows NO specific chess rules.
# ---------------------------------------------------------------------------


# ===========================================================================
# Abstract interface
# ===========================================================================

class MovementRule(ABC):
    """Abstract Strategy for validating move geometry.

    Subclasses encode pure shape logic (no board state).
    Board-aware checks (path obstruction) live in ``MoveValidator``.
    """

    @abstractmethod
    def is_valid_shape(self, from_pos: Position, to_pos: Position) -> bool:
        """Return True iff the displacement is geometrically legal."""

    @property
    @abstractmethod
    def is_sliding(self) -> bool:
        """True iff this piece glides along a ray and can be blocked."""


# ===========================================================================
# Concrete movement rules
# ===========================================================================

class OrthogonalMove(MovementRule):
    """Horizontal or vertical movement, any distance.  Used by Rook."""

    @property
    def is_sliding(self) -> bool:
        return True

    def is_valid_shape(self, from_pos: Position, to_pos: Position) -> bool:
        dr = to_pos.row - from_pos.row
        dc = to_pos.col - from_pos.col
        # Exactly one axis moves (XOR).
        return (dr == 0) != (dc == 0)


class DiagonalMove(MovementRule):
    """Diagonal movement, any distance.  Used by Bishop."""

    @property
    def is_sliding(self) -> bool:
        return True

    def is_valid_shape(self, from_pos: Position, to_pos: Position) -> bool:
        dr = abs(to_pos.row - from_pos.row)
        dc = abs(to_pos.col - from_pos.col)
        return dr == dc and dr > 0


class LShapeMove(MovementRule):
    """L-shaped (Knight) movement.  Jumps — never blocked by intermediates."""

    @property
    def is_sliding(self) -> bool:
        return False

    def is_valid_shape(self, from_pos: Position, to_pos: Position) -> bool:
        dr = abs(to_pos.row - from_pos.row)
        dc = abs(to_pos.col - from_pos.col)
        return (dr, dc) in {(1, 2), (2, 1)}


class CompositeMove(MovementRule):
    """Accepts a move that is valid under *any* of the composed rules.

    ``is_sliding`` is True if at least one component rule is sliding.
    Typical use: Queen = CompositeMove(OrthogonalMove(), DiagonalMove()).
    """

    def __init__(self, *rules: MovementRule) -> None:
        self._rules: tuple[MovementRule, ...] = rules

    @property
    def is_sliding(self) -> bool:
        return any(r.is_sliding for r in self._rules)

    def is_valid_shape(self, from_pos: Position, to_pos: Position) -> bool:
        return any(r.is_valid_shape(from_pos, to_pos) for r in self._rules)


class OneStepMove(MovementRule):
    """Wraps any rule and restricts it to a single step (Chebyshev distance = 1).

    Used by the King: Queen directions, but only one square at a time.
    Never sliding — no intermediate squares exist after a 1-step move.
    """

    def __init__(self, inner: MovementRule) -> None:
        self._inner = inner

    @property
    def is_sliding(self) -> bool:
        return False

    def is_valid_shape(self, from_pos: Position, to_pos: Position) -> bool:
        dr = abs(to_pos.row - from_pos.row)
        dc = abs(to_pos.col - from_pos.col)
        return max(dr, dc) == 1 and self._inner.is_valid_shape(from_pos, to_pos)


# ===========================================================================
# Default rule registry
# ===========================================================================

_QUEEN_MOVE: MovementRule = CompositeMove(OrthogonalMove(), DiagonalMove())

_DEFAULT_RULES: dict[str, MovementRule] = {
    "R": OrthogonalMove(),
    "B": DiagonalMove(),
    "Q": _QUEEN_MOVE,
    "N": LShapeMove(),
    "K": OneStepMove(_QUEEN_MOVE),   # Queen shape restricted to 1 step
}


# ===========================================================================
# MoveValidator
# ===========================================================================

class MoveValidator:
    """Registry-based move validator.

    Maps piece-type characters (``"K"``, ``"R"``, …) to ``MovementRule``
    instances.  Open for extension via ``register()`` — add or replace rules
    at runtime without modifying this class or the Engine.

    The Engine calls ``is_valid()`` and has zero knowledge of chess rules.
    """

    def __init__(self, rules: dict[str, MovementRule] | None = None) -> None:
        # Defensive copy so callers cannot mutate the module-level defaults.
        self._rules: dict[str, MovementRule] = dict(
            _DEFAULT_RULES if rules is None else rules
        )

    def register(self, piece_type: str, rule: MovementRule) -> None:
        """Register or replace the ``MovementRule`` for *piece_type*.

        This is the OCP extension point: new or modified piece behaviour
        requires only calling this method — no existing code changes.
        """
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
        piece_type = piece[1]           # "wK" → "K", "bR" → "R"
        rule = self._rules.get(piece_type)
        if rule is None:
            return False
        if not rule.is_valid_shape(from_pos, to_pos):
            return False
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
        r = from_pos.row + step_r
        c = from_pos.col + step_c
        while (r, c) != (to_pos.row, to_pos.col):
            if board.get_piece_at(Position(r, c)) != ".":
                return False
            r += step_r
            c += step_c
        return True
