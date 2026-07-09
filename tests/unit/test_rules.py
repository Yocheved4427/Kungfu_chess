"""
Unit tests for engine/rules.py  (Strategy Pattern / OCP)

Coverage plan
-------------
  MovementRule subclasses   is_valid_shape + is_sliding for every concrete type
  PawnRule                  is_valid_shape (loose) + is_valid_with_context (full)
  _CompositeRule             union semantics; is_sliding propagation
  KingRule                  one-step restriction; is_sliding always False
  MoveValidator.register    OCP extension point
  MoveValidator.is_valid    full dispatch: context check → friendly-fire → path
  _path_clear (via is_valid) clear path, blocked mid, blocked last, adjacent
"""

from __future__ import annotations

import pytest

from core.models import Position
from engine.board import TextBoard
from engine.rules import (
    DiagonalRule,
    KingRule,
    KnightRule,
    MoveValidator,
    MovementRule,
    OrthogonalRule,
    PawnRule,
    _CompositeRule,
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

    def test_default_context_check_delegates_to_shape(self):
        """A rule that doesn't override is_valid_with_context falls back to
        is_valid_shape, ignoring the destination content entirely."""
        rule = OrthogonalRule()
        assert rule.is_valid_with_context(
            "wR", Position(0, 0), Position(0, 3), dest_piece="bP"
        ) is True


# ===========================================================================
# OrthogonalRule
# ===========================================================================

class TestOrthogonalRule:
    def setup_method(self):
        self.rule = OrthogonalRule()

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
# DiagonalRule
# ===========================================================================

class TestDiagonalRule:
    def setup_method(self):
        self.rule = DiagonalRule()

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
# KnightRule
# ===========================================================================

class TestKnightRule:
    def setup_method(self):
        self.rule = KnightRule()

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
# _CompositeRule  (internal helper — tested directly as a white-box unit
# since it backs both Queen and King and its union semantics are non-trivial)
# ===========================================================================

class TestCompositeRule:
    def test_is_sliding_true_if_any_component_sliding(self):
        c = _CompositeRule(KnightRule(), OrthogonalRule())
        assert c.is_sliding is True

    def test_is_sliding_false_if_all_non_sliding(self):
        c = _CompositeRule(KnightRule(), KnightRule())
        assert c.is_sliding is False

    def test_accepts_move_valid_in_first_rule(self):
        c = _CompositeRule(OrthogonalRule(), DiagonalRule())
        # Orthogonal move → valid via first rule
        assert c.is_valid_shape(Position(0, 0), Position(0, 3)) is True

    def test_accepts_move_valid_in_second_rule(self):
        c = _CompositeRule(OrthogonalRule(), DiagonalRule())
        # Diagonal move → valid via second rule
        assert c.is_valid_shape(Position(0, 0), Position(2, 2)) is True

    def test_rejects_move_invalid_in_all_rules(self):
        c = _CompositeRule(OrthogonalRule(), DiagonalRule())
        # L-shape → invalid in both rules
        assert c.is_valid_shape(Position(0, 0), Position(1, 2)) is False

    def test_single_rule_composite(self):
        c = _CompositeRule(KnightRule())
        assert c.is_valid_shape(Position(0, 0), Position(1, 2)) is True


# ===========================================================================
# KingRule
# ===========================================================================

class TestKingRule:
    def setup_method(self):
        self.rule = KingRule()

    def test_is_not_sliding(self):
        assert self.rule.is_sliding is False

    def test_one_step_orthogonal_valid(self):
        assert self.rule.is_valid_shape(Position(1, 1), Position(1, 2)) is True

    def test_one_step_diagonal_valid(self):
        assert self.rule.is_valid_shape(Position(1, 1), Position(2, 2)) is True

    def test_all_eight_directions_valid(self):
        from_pos = Position(3, 3)
        for dr, dc in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
            assert self.rule.is_valid_shape(
                from_pos, Position(3 + dr, 3 + dc)
            ) is True, f"King one-step ({dr},{dc}) should be valid"

    def test_two_steps_orthogonal_invalid(self):
        assert self.rule.is_valid_shape(Position(0, 0), Position(0, 2)) is False

    def test_two_steps_diagonal_invalid(self):
        assert self.rule.is_valid_shape(Position(0, 0), Position(2, 2)) is False

    def test_same_position_invalid(self):
        assert self.rule.is_valid_shape(Position(1, 1), Position(1, 1)) is False

    def test_l_shape_invalid(self):
        assert self.rule.is_valid_shape(Position(0, 0), Position(1, 2)) is False


# ===========================================================================
# PawnRule
# ===========================================================================

class TestPawnRuleShape:
    """is_valid_shape is the loose, board-agnostic geometry check: one step
    forward or diagonal, colour-blind."""

    def setup_method(self):
        self.rule = PawnRule()

    def test_is_not_sliding(self):
        assert self.rule.is_sliding is False

    def test_one_step_forward_valid(self):
        assert self.rule.is_valid_shape(Position(1, 1), Position(2, 1)) is True

    def test_one_step_backward_also_valid_shape(self):
        """Shape check is direction-agnostic; direction is enforced only in
        is_valid_with_context."""
        assert self.rule.is_valid_shape(Position(1, 1), Position(0, 1)) is True

    def test_one_step_diagonal_valid(self):
        assert self.rule.is_valid_shape(Position(1, 1), Position(2, 2)) is True

    def test_two_steps_forward_invalid(self):
        assert self.rule.is_valid_shape(Position(1, 1), Position(3, 1)) is False

    def test_sideways_invalid(self):
        assert self.rule.is_valid_shape(Position(1, 1), Position(1, 2)) is False

    def test_same_position_invalid(self):
        assert self.rule.is_valid_shape(Position(1, 1), Position(1, 1)) is False


class TestPawnRuleContext:
    """is_valid_with_context enforces colour direction and destination content."""

    def setup_method(self):
        self.rule = PawnRule()

    def test_white_forward_onto_empty_valid(self):
        assert self.rule.is_valid_with_context(
            "wP", Position(6, 4), Position(5, 4), dest_piece="."
        ) is True

    def test_white_forward_onto_occupied_invalid(self):
        assert self.rule.is_valid_with_context(
            "wP", Position(6, 4), Position(5, 4), dest_piece="bP"
        ) is False

    def test_white_diagonal_capture_valid(self):
        assert self.rule.is_valid_with_context(
            "wP", Position(6, 4), Position(5, 5), dest_piece="bN"
        ) is True

    def test_white_diagonal_onto_empty_invalid(self):
        assert self.rule.is_valid_with_context(
            "wP", Position(6, 4), Position(5, 5), dest_piece="."
        ) is False

    def test_white_backward_invalid(self):
        assert self.rule.is_valid_with_context(
            "wP", Position(6, 4), Position(7, 4), dest_piece="."
        ) is False

    def test_black_forward_onto_empty_valid(self):
        assert self.rule.is_valid_with_context(
            "bP", Position(1, 4), Position(2, 4), dest_piece="."
        ) is True

    def test_black_forward_direction_is_reversed_from_white(self):
        """Black moving in white's forward direction (decreasing row) is invalid."""
        assert self.rule.is_valid_with_context(
            "bP", Position(1, 4), Position(0, 4), dest_piece="."
        ) is False

    def test_black_diagonal_capture_valid(self):
        assert self.rule.is_valid_with_context(
            "bP", Position(1, 4), Position(2, 5), dest_piece="wN"
        ) is True


# ===========================================================================
# MoveValidator — OCP extension point
# ===========================================================================

class TestMoveValidatorRegister:
    def test_register_new_piece_type(self):
        """A custom 'X' piece that moves like a Knight is registerable."""
        v = MoveValidator()
        v.register("X", KnightRule())
        b = _b(". . . . .", ". . . . .", ". . wX . .", ". . . . .", ". . . . .")
        assert v.is_valid("wX", Position(2, 2), Position(0, 1), b) is True

    def test_replace_existing_rule(self):
        """Replacing Rook's rule with a KnightRule changes its behaviour."""

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
        v.register("Z", _AlwaysValid())
        b = _b("wZ .")
        assert v.is_valid("wZ", Position(0, 0), Position(0, 1), b) is True

    def test_register_overrides_default_pawn_rule(self):
        """Registering over an already-default-registered piece type (Pawn)
        replaces its behaviour entirely."""

        class _AlwaysValid(MovementRule):
            @property
            def is_sliding(self) -> bool:
                return False

            def is_valid_shape(self, *_) -> bool:
                return True

        v = MoveValidator()
        v.register("P", _AlwaysValid())
        b = _b("wP .")
        # Sideways is illegal for a real pawn, but the override accepts anything.
        assert v.is_valid("wP", Position(0, 0), Position(0, 1), b) is True

    def test_default_registry_is_not_mutated_by_instance(self):
        """Two separate validators are independent."""
        v1 = MoveValidator()
        v2 = MoveValidator()
        v1.register("R", KnightRule())  # v1 Rook now behaves like Knight
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
        # All intermediate squares filled, but Knight jumps. Destination is an
        # enemy piece (not a friendly one) so the move is a legal capture.
        board = TextBoard(["bP bP bP bP", "wP wP wP wP", "wP wN wP wP", "wP wP wP ."])
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


class TestMoveValidatorPawn:
    """White's forward direction is decreasing row (toward row 0); Black's
    forward direction is increasing row — see PawnRule.is_valid_with_context."""

    def setup_method(self):
        self.v = MoveValidator()

    def test_white_forward_onto_empty_valid(self):
        b = _b(". .", "wP .")
        assert self.v.is_valid("wP", Position(1, 0), Position(0, 0), b) is True

    def test_white_forward_onto_occupied_invalid(self):
        b = _b("bP .", "wP .")
        assert self.v.is_valid("wP", Position(1, 0), Position(0, 0), b) is False

    def test_white_diagonal_capture_forward_valid(self):
        b = _b(". bN", "wP .")
        assert self.v.is_valid("wP", Position(1, 0), Position(0, 1), b) is True

    def test_white_diagonal_onto_empty_invalid(self):
        b = _b(". .", "wP .")
        assert self.v.is_valid("wP", Position(1, 0), Position(0, 1), b) is False

    def test_white_diagonal_onto_own_piece_invalid(self):
        b = _b(". wN", "wP .")
        assert self.v.is_valid("wP", Position(1, 0), Position(0, 1), b) is False

    def test_white_two_steps_invalid(self):
        b = _b(". .", ". .", "wP .")
        assert self.v.is_valid("wP", Position(2, 0), Position(0, 0), b) is False

    def test_white_backward_invalid(self):
        b = _b("wP .", ". .")
        assert self.v.is_valid("wP", Position(0, 0), Position(1, 0), b) is False

    def test_black_forward_onto_empty_valid(self):
        b = _b("bP .", ". .")
        assert self.v.is_valid("bP", Position(0, 0), Position(1, 0), b) is True

    def test_black_forward_onto_occupied_invalid(self):
        b = _b("bP .", "wP .")
        assert self.v.is_valid("bP", Position(0, 0), Position(1, 0), b) is False

    def test_black_diagonal_capture_forward_valid(self):
        b = _b("bP .", ". wN")
        assert self.v.is_valid("bP", Position(0, 0), Position(1, 1), b) is True

    def test_black_backward_invalid(self):
        b = _b(". .", "bP .")
        assert self.v.is_valid("bP", Position(1, 0), Position(0, 0), b) is False


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
