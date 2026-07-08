"""
Unit tests for src/rules.py  (Iteration 3 — OCP class hierarchy)

Coverage plan
-------------
  MovementRule subclasses   is_valid_shape + is_sliding for every concrete type
  CompositeMove             union semantics; is_sliding propagation
  OneStepMove               step restriction; is_sliding always False
  MoveValidator.register    OCP extension point
  MoveValidator.is_valid    full dispatch: shape check → path check per piece type
  _path_clear (via is_valid) clear path, blocked mid, blocked last, adjacent
"""

from __future__ import annotations

import pytest

from src.board import TextBoard
from src.models import Position
from src.rules import (
    CompositeMove,
    DiagonalMove,
    LShapeMove,
    MoveValidator,
    MovementRule,
    OneStepMove,
    OrthogonalMove,
)


# ---------------------------------------------------------------------------
# Board factory shorthand
# ---------------------------------------------------------------------------

def _b(*rows: str) -> TextBoard:
    return TextBoard(list(rows))


# ===========================================================================
# MovementRule ABC
# ===========================================================================

class TestMovementRuleABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            MovementRule()  # type: ignore[abstract]


# ===========================================================================
# OrthogonalMove
# ===========================================================================

class TestOrthogonalMove:
    def setup_method(self):
        self.rule = OrthogonalMove()

    def test_is_sliding(self):
        assert self.rule.is_sliding is True

    def test_horizontal_right(self):
        assert self.rule.is_valid_shape(Position(0, 0), Position(0, 4)) is True

    def test_horizontal_left(self):
        assert self.rule.is_valid_shape(Position(0, 4), Position(0, 0)) is True

    def test_vertical_down(self):
        assert self.rule.is_valid_shape(Position(0, 0), Position(5, 0)) is True

    def test_vertical_up(self):
        assert self.rule.is_valid_shape(Position(5, 0), Position(0, 0)) is True

    def test_one_step_right(self):
        assert self.rule.is_valid_shape(Position(0, 0), Position(0, 1)) is True

    def test_diagonal_invalid(self):
        assert self.rule.is_valid_shape(Position(0, 0), Position(3, 3)) is False

    def test_l_shape_invalid(self):
        assert self.rule.is_valid_shape(Position(0, 0), Position(1, 2)) is False

    def test_same_position_invalid(self):
        assert self.rule.is_valid_shape(Position(2, 2), Position(2, 2)) is False


# ===========================================================================
# DiagonalMove
# ===========================================================================

class TestDiagonalMove:
    def setup_method(self):
        self.rule = DiagonalMove()

    def test_is_sliding(self):
        assert self.rule.is_sliding is True

    def test_southeast(self):
        assert self.rule.is_valid_shape(Position(0, 0), Position(3, 3)) is True

    def test_southwest(self):
        assert self.rule.is_valid_shape(Position(0, 3), Position(3, 0)) is True

    def test_northeast(self):
        assert self.rule.is_valid_shape(Position(3, 0), Position(0, 3)) is True

    def test_northwest(self):
        assert self.rule.is_valid_shape(Position(3, 3), Position(0, 0)) is True

    def test_one_step_diagonal(self):
        assert self.rule.is_valid_shape(Position(1, 1), Position(2, 2)) is True

    def test_horizontal_invalid(self):
        assert self.rule.is_valid_shape(Position(0, 0), Position(0, 3)) is False

    def test_vertical_invalid(self):
        assert self.rule.is_valid_shape(Position(0, 0), Position(3, 0)) is False

    def test_non_proportional_invalid(self):
        assert self.rule.is_valid_shape(Position(0, 0), Position(1, 2)) is False

    def test_same_position_invalid(self):
        assert self.rule.is_valid_shape(Position(1, 1), Position(1, 1)) is False


# ===========================================================================
# LShapeMove
# ===========================================================================

class TestLShapeMove:
    def setup_method(self):
        self.rule = LShapeMove()

    def test_is_not_sliding(self):
        assert self.rule.is_sliding is False

    def test_all_eight_l_shapes(self):
        targets = [
            (-2, -1), (-2, 1), (-1, -2), (-1, 2),
            (1, -2),  (1, 2),  (2, -1),  (2, 1),
        ]
        from_pos = Position(3, 3)
        for dr, dc in targets:
            assert self.rule.is_valid_shape(
                from_pos, Position(3 + dr, 3 + dc)
            ) is True, f"Knight L-shape ({dr},{dc}) should be valid"

    def test_straight_invalid(self):
        assert self.rule.is_valid_shape(Position(0, 0), Position(0, 2)) is False

    def test_diagonal_invalid(self):
        assert self.rule.is_valid_shape(Position(0, 0), Position(2, 2)) is False

    def test_same_position_invalid(self):
        assert self.rule.is_valid_shape(Position(1, 1), Position(1, 1)) is False


# ===========================================================================
# CompositeMove
# ===========================================================================

class TestCompositeMove:
    def test_is_sliding_true_if_any_component_sliding(self):
        c = CompositeMove(LShapeMove(), OrthogonalMove())
        assert c.is_sliding is True

    def test_is_sliding_false_if_all_non_sliding(self):
        c = CompositeMove(LShapeMove(), LShapeMove())
        assert c.is_sliding is False

    def test_accepts_move_valid_in_first_rule(self):
        c = CompositeMove(OrthogonalMove(), DiagonalMove())
        # Orthogonal move → valid via first rule
        assert c.is_valid_shape(Position(0, 0), Position(0, 3)) is True

    def test_accepts_move_valid_in_second_rule(self):
        c = CompositeMove(OrthogonalMove(), DiagonalMove())
        # Diagonal move → valid via second rule
        assert c.is_valid_shape(Position(0, 0), Position(2, 2)) is True

    def test_rejects_move_invalid_in_all_rules(self):
        c = CompositeMove(OrthogonalMove(), DiagonalMove())
        # L-shape → invalid in both rules
        assert c.is_valid_shape(Position(0, 0), Position(1, 2)) is False

    def test_single_rule_composite(self):
        c = CompositeMove(LShapeMove())
        assert c.is_valid_shape(Position(0, 0), Position(1, 2)) is True


# ===========================================================================
# OneStepMove
# ===========================================================================

class TestOneStepMove:
    def setup_method(self):
        # King = one-step in any Queen direction
        self.king_rule = OneStepMove(CompositeMove(OrthogonalMove(), DiagonalMove()))

    def test_is_not_sliding_even_when_inner_is_sliding(self):
        assert self.king_rule.is_sliding is False

    def test_one_step_orthogonal_valid(self):
        assert self.king_rule.is_valid_shape(Position(1, 1), Position(1, 2)) is True

    def test_one_step_diagonal_valid(self):
        assert self.king_rule.is_valid_shape(Position(1, 1), Position(2, 2)) is True

    def test_all_eight_directions_valid(self):
        from_pos = Position(3, 3)
        for dr, dc in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
            assert self.king_rule.is_valid_shape(
                from_pos, Position(3 + dr, 3 + dc)
            ) is True, f"King one-step ({dr},{dc}) should be valid"

    def test_two_steps_orthogonal_invalid(self):
        assert self.king_rule.is_valid_shape(Position(0, 0), Position(0, 2)) is False

    def test_two_steps_diagonal_invalid(self):
        assert self.king_rule.is_valid_shape(Position(0, 0), Position(2, 2)) is False

    def test_same_position_invalid(self):
        assert self.king_rule.is_valid_shape(Position(1, 1), Position(1, 1)) is False

    def test_l_shape_invalid_even_if_inner_would_allow(self):
        # inner = CompositeMove with LShapeMove; OneStep still limits distance
        rule = OneStepMove(LShapeMove())
        assert rule.is_valid_shape(Position(0, 0), Position(1, 2)) is False


# ===========================================================================
# MoveValidator — OCP extension point
# ===========================================================================

class TestMoveValidatorRegister:
    def test_register_new_piece_type(self):
        """A custom 'X' piece that moves like a Knight is registerable."""
        v = MoveValidator()
        v.register("X", LShapeMove())
        b = _b(". . . . .", ". . . . .", ". . wX . .", ". . . . .", ". . . . .")
        assert v.is_valid("wX", Position(2, 2), Position(0, 1), b) is True

    def test_replace_existing_rule(self):
        """Replacing Rook's rule with LShapeMove changes its behaviour."""

        class _AlwaysInvalid(MovementRule):
            @property
            def is_sliding(self) -> bool:
                return False

            def is_valid_shape(self, *_) -> bool:
                return False

        v = MoveValidator()
        v.register("R", _AlwaysInvalid())
        b = _b("wR . . .")
        assert v.is_valid("wR", Position(0, 0), Position(0, 3), b) is False

    def test_register_accepts_any_movementrule_subclass(self):
        class _AlwaysValid(MovementRule):
            @property
            def is_sliding(self) -> bool:
                return False

            def is_valid_shape(self, *_) -> bool:
                return True

        v = MoveValidator()
        v.register("P", _AlwaysValid())
        b = _b("wP .")
        assert v.is_valid("wP", Position(0, 0), Position(0, 1), b) is True

    def test_default_registry_is_not_mutated_by_instance(self):
        """Two separate validators are independent."""
        v1 = MoveValidator()
        v2 = MoveValidator()
        v1.register("R", LShapeMove())  # v1 Rook now behaves like Knight
        # v2 Rook must still be orthogonal
        b = _b("wR . . .")
        assert v2.is_valid("wR", Position(0, 0), Position(0, 3), b) is True


# ===========================================================================
# MoveValidator — full is_valid dispatch
# ===========================================================================

class TestMoveValidatorSamePosition:
    def test_same_position_always_invalid(self):
        v = MoveValidator()
        b = _b("wK .")
        assert v.is_valid("wK", Position(0, 0), Position(0, 0), b) is False


class TestMoveValidatorUnknownPiece:
    def test_pawn_not_registered_returns_false(self):
        v = MoveValidator()
        b = _b("wP .")
        assert v.is_valid("wP", Position(0, 0), Position(0, 1), b) is False

    def test_unknown_char_returns_false(self):
        v = MoveValidator()
        b = _b("wX .")
        assert v.is_valid("wX", Position(0, 0), Position(0, 1), b) is False


class TestMoveValidatorKing:
    def setup_method(self):
        self.v = MoveValidator()

    def test_one_step_any_direction(self):
        b = _b(". . .", ". wK .", ". . .")
        for dr, dc in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
            assert self.v.is_valid(
                "wK", Position(1, 1), Position(1+dr, 1+dc), b
            ) is True

    def test_two_steps_invalid(self):
        b = _b("wK . . .")
        assert self.v.is_valid("wK", Position(0, 0), Position(0, 2), b) is False

    def test_black_king_valid(self):
        b = _b("bK .")
        assert self.v.is_valid("bK", Position(0, 0), Position(0, 1), b) is True


class TestMoveValidatorKnight:
    def setup_method(self):
        self.v = MoveValidator()
        self.board = TextBoard([". . . . ."] * 5)

    def test_all_eight_l_shapes(self):
        targets = [(0,1),(0,3),(4,1),(4,3),(1,0),(3,0),(1,4),(3,4)]
        for r, c in targets:
            assert self.v.is_valid(
                "wN", Position(2, 2), Position(r, c), self.board
            ) is True, f"Knight should reach ({r},{c})"

    def test_straight_invalid(self):
        assert self.v.is_valid("wN", Position(2, 2), Position(2, 3), self.board) is False

    def test_knight_jumps_over_pieces(self):
        # All intermediate squares filled, but Knight jumps
        board = TextBoard(["wP wP wP wP", "wP wP wP wP", "wP wN wP wP", "wP wP wP ."])
        # (2,1) → (0,2) is dr=-2, dc=1 — valid L-shape, jumps over filled squares
        assert self.v.is_valid("wN", Position(2, 1), Position(0, 2), board) is True


class TestMoveValidatorRook:
    def setup_method(self):
        self.v = MoveValidator()

    def test_horizontal_clear(self):
        b = _b("wR . . .")
        assert self.v.is_valid("wR", Position(0, 0), Position(0, 3), b) is True

    def test_vertical_clear(self):
        b = _b("wR", ".", ".")
        assert self.v.is_valid("wR", Position(0, 0), Position(2, 0), b) is True

    def test_diagonal_invalid(self):
        b = _b("wR . .", ". . .", ". . .")
        assert self.v.is_valid("wR", Position(0, 0), Position(2, 2), b) is False

    def test_blocked_horizontal(self):
        b = _b("wR bP . .")
        assert self.v.is_valid("wR", Position(0, 0), Position(0, 3), b) is False

    def test_blocked_vertical(self):
        b = _b("wR", "bP", ".")
        assert self.v.is_valid("wR", Position(0, 0), Position(2, 0), b) is False

    def test_adjacent_never_blocked(self):
        b = _b("wR .")
        assert self.v.is_valid("wR", Position(0, 0), Position(0, 1), b) is True


class TestMoveValidatorBishop:
    def setup_method(self):
        self.v = MoveValidator()

    def test_diagonal_clear(self):
        b = _b("wB . .", ". . .", ". . .")
        assert self.v.is_valid("wB", Position(0, 0), Position(2, 2), b) is True

    def test_horizontal_invalid(self):
        b = _b("wB . .")
        assert self.v.is_valid("wB", Position(0, 0), Position(0, 2), b) is False

    def test_blocked_diagonal(self):
        b = _b("wB . .", ". bP .", ". . .")
        assert self.v.is_valid("wB", Position(0, 0), Position(2, 2), b) is False

    def test_backward_diagonal(self):
        b = _b(". . wB", ". . .", ". . .")
        assert self.v.is_valid("wB", Position(0, 2), Position(2, 0), b) is True


class TestMoveValidatorQueen:
    def setup_method(self):
        self.v = MoveValidator()

    def test_horizontal(self):
        b = _b("wQ . . .")
        assert self.v.is_valid("wQ", Position(0, 0), Position(0, 3), b) is True

    def test_vertical(self):
        b = _b("wQ", ".", ".")
        assert self.v.is_valid("wQ", Position(0, 0), Position(2, 0), b) is True

    def test_diagonal(self):
        b = _b("wQ . .", ". . .", ". . .")
        assert self.v.is_valid("wQ", Position(0, 0), Position(2, 2), b) is True

    def test_l_shape_invalid(self):
        b = TextBoard([". . . . ."] * 3)
        assert self.v.is_valid("wQ", Position(0, 0), Position(1, 2), b) is False

    def test_blocked_horizontal(self):
        b = _b("wQ bP . .")
        assert self.v.is_valid("wQ", Position(0, 0), Position(0, 3), b) is False

    def test_blocked_diagonal(self):
        b = _b("wQ . .", ". bP .", ". . .")
        assert self.v.is_valid("wQ", Position(0, 0), Position(2, 2), b) is False


# ===========================================================================
# _path_clear (tested indirectly via MoveValidator.is_valid)
# ===========================================================================

class TestPathClearViaValidator:
    def setup_method(self):
        self.v = MoveValidator()

    def test_adjacent_always_clear(self):
        b = _b("wR .")
        assert self.v.is_valid("wR", Position(0, 0), Position(0, 1), b) is True

    def test_blocked_first_intermediate(self):
        b = _b("wR bP . .")
        assert self.v.is_valid("wR", Position(0, 0), Position(0, 3), b) is False

    def test_blocked_last_intermediate(self):
        b = _b("wR . bP .")
        assert self.v.is_valid("wR", Position(0, 0), Position(0, 3), b) is False

    def test_clear_multi_step_vertical(self):
        b = _b("wR", ".", ".", ".")
        assert self.v.is_valid("wR", Position(0, 0), Position(3, 0), b) is True

    def test_upward_move_clear(self):
        b = _b(".", ".", "wR")
        assert self.v.is_valid("wR", Position(2, 0), Position(0, 0), b) is True

    def test_upward_move_blocked(self):
        b = _b(".", "bP", "wR")
        assert self.v.is_valid("wR", Position(2, 0), Position(0, 0), b) is False



# ---------------------------------------------------------------------------
