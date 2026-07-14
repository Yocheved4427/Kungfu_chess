"""
Unit tests for engine/rule_engine.py

Scope: RuleEngine and its per-piece-type IPieceRule strategies, entirely
independent of GameEngine / engine.rules — this is a standalone Strategy
implementation with a richer MoveResult-enum API instead of a bare bool.

Coverage plan
-------------
  MoveResult                is_ok predicate
  Per-piece IPieceRule       is_legal_move + requires_path_check, in isolation
  RuleEngine.validate_move   every MoveResult branch, for every piece type
  RuleEngine.register        OCP extension point
"""

from __future__ import annotations

import pytest

from core.models import Position
from engine.board import TextBoard
from engine.rule_engine import (
    BishopRule,
    IPieceRule,
    KingRule,
    KnightRule,
    MoveResult,
    PawnRule,
    QueenRule,
    RookRule,
    RuleEngine,
)


def _b(*rows: str) -> TextBoard:
    return TextBoard(list(rows))


# ===========================================================================
# MoveResult
# ===========================================================================

class TestMoveResult:
    def test_ok_is_ok(self):
        assert MoveResult.OK.is_ok is True

    @pytest.mark.parametrize(
        "member",
        [
            MoveResult.OUTSIDE_BOARD,
            MoveResult.SAME_POSITION,
            MoveResult.EMPTY_SOURCE,
            MoveResult.UNKNOWN_PIECE_TYPE,
            MoveResult.ILLEGAL_PATTERN,
            MoveResult.FRIENDLY_FIRE,
            MoveResult.BLOCKED_PATH,
            MoveResult.GAME_OVER,
        ],
    )
    def test_every_other_member_is_not_ok(self, member):
        assert member.is_ok is False

    def test_members_are_distinct(self):
        assert len(set(MoveResult)) == 9

    def test_validate_move_never_produces_game_over(self):
        """GAME_OVER exists solely for GameEngine.try_move — RuleEngine
        itself has no notion of game-over state, so validate_move must
        never return it, no matter the board."""
        engine = RuleEngine()
        board = _b("wR . .")
        result = engine.validate_move("wR", Position(0, 0), Position(0, 1), board)
        assert result != MoveResult.GAME_OVER


# ===========================================================================
# IPieceRule ABC
# ===========================================================================

class TestIPieceRuleABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            IPieceRule()  # type: ignore[abstract]

    def test_default_requires_path_check_is_false(self):
        class _Minimal(IPieceRule):
            def is_legal_move(self, piece, from_pos, to_pos, board) -> bool:
                return True

        assert _Minimal().requires_path_check(Position(0, 0), Position(0, 1)) is False


# ===========================================================================
# RookRule
# ===========================================================================

class TestRookRule:
    def setup_method(self):
        self.rule = RookRule()
        self.board = _b("wR . . .")

    def test_horizontal_is_legal(self):
        assert self.rule.is_legal_move("wR", Position(0, 0), Position(0, 3), self.board) is True

    def test_vertical_is_legal(self):
        assert self.rule.is_legal_move("wR", Position(0, 0), Position(5, 0), self.board) is True

    def test_diagonal_is_illegal(self):
        assert self.rule.is_legal_move("wR", Position(0, 0), Position(3, 3), self.board) is False

    def test_no_movement_is_illegal(self):
        assert self.rule.is_legal_move("wR", Position(2, 2), Position(2, 2), self.board) is False

    def test_requires_path_check(self):
        assert self.rule.requires_path_check(Position(0, 0), Position(0, 3)) is True


# ===========================================================================
# BishopRule
# ===========================================================================

class TestBishopRule:
    def setup_method(self):
        self.rule = BishopRule()
        self.board = _b("wB . . .")

    def test_diagonal_is_legal(self):
        assert self.rule.is_legal_move("wB", Position(0, 0), Position(3, 3), self.board) is True

    def test_orthogonal_is_illegal(self):
        assert self.rule.is_legal_move("wB", Position(0, 0), Position(0, 3), self.board) is False

    def test_uneven_diagonal_is_illegal(self):
        assert self.rule.is_legal_move("wB", Position(0, 0), Position(1, 2), self.board) is False

    def test_requires_path_check(self):
        assert self.rule.requires_path_check(Position(0, 0), Position(3, 3)) is True


# ===========================================================================
# QueenRule
# ===========================================================================

class TestQueenRule:
    def setup_method(self):
        self.rule = QueenRule()
        self.board = _b("wQ . . .")

    def test_orthogonal_is_legal(self):
        assert self.rule.is_legal_move("wQ", Position(0, 0), Position(0, 3), self.board) is True

    def test_diagonal_is_legal(self):
        assert self.rule.is_legal_move("wQ", Position(0, 0), Position(2, 2), self.board) is True

    def test_knight_shape_is_illegal(self):
        assert self.rule.is_legal_move("wQ", Position(0, 0), Position(1, 2), self.board) is False

    def test_requires_path_check(self):
        assert self.rule.requires_path_check(Position(0, 0), Position(0, 3)) is True


# ===========================================================================
# KnightRule
# ===========================================================================

class TestKnightRule:
    def setup_method(self):
        self.rule = KnightRule()
        self.board = _b(". . . . .", ". . . . .", ". . wN . .", ". . . . .", ". . . . .")

    @pytest.mark.parametrize("dr,dc", [(1, 2), (2, 1), (-1, 2), (-2, -1), (1, -2), (-1, -2)])
    def test_l_shapes_are_legal(self, dr, dc):
        assert self.rule.is_legal_move(
            "wN", Position(2, 2), Position(2 + dr, 2 + dc), self.board
        ) is True

    def test_straight_line_is_illegal(self):
        assert self.rule.is_legal_move("wN", Position(2, 2), Position(2, 4), self.board) is False

    def test_does_not_require_path_check(self):
        assert self.rule.requires_path_check(Position(2, 2), Position(0, 1)) is False


# ===========================================================================
# KingRule
# ===========================================================================

class TestKingRule:
    def setup_method(self):
        self.rule = KingRule()
        self.board = _b(". . .", ". wK .", ". . .")

    @pytest.mark.parametrize(
        "dr,dc", [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    )
    def test_one_step_any_direction_is_legal(self, dr, dc):
        assert self.rule.is_legal_move(
            "wK", Position(1, 1), Position(1 + dr, 1 + dc), self.board
        ) is True

    def test_two_steps_is_illegal(self):
        board = _b("wK . .")
        assert self.rule.is_legal_move("wK", Position(0, 0), Position(0, 2), board) is False

    def test_does_not_require_path_check(self):
        assert self.rule.requires_path_check(Position(1, 1), Position(1, 2)) is False


# ===========================================================================
# PawnRule
# ===========================================================================

class TestPawnRule:
    def setup_method(self):
        self.rule = PawnRule()

    # -- one-step forward --------------------------------------------------

    def test_white_forward_onto_empty_is_legal(self):
        board = _b(". .", "wP .")
        assert self.rule.is_legal_move("wP", Position(1, 0), Position(0, 0), board) is True

    def test_white_forward_onto_occupied_is_illegal(self):
        board = _b("bP .", "wP .")
        assert self.rule.is_legal_move("wP", Position(1, 0), Position(0, 0), board) is False

    def test_black_forward_onto_empty_is_legal(self):
        board = _b("bP .", ". .")
        assert self.rule.is_legal_move("bP", Position(0, 0), Position(1, 0), board) is True

    def test_white_backward_is_illegal(self):
        board = _b("wP .", ". .")
        assert self.rule.is_legal_move("wP", Position(0, 0), Position(1, 0), board) is False

    # -- diagonal capture ----------------------------------------------------

    def test_diagonal_capture_onto_enemy_is_legal(self):
        board = _b(". bN", "wP .")
        assert self.rule.is_legal_move("wP", Position(1, 0), Position(0, 1), board) is True

    def test_diagonal_onto_empty_is_illegal(self):
        board = _b(". .", "wP .")
        assert self.rule.is_legal_move("wP", Position(1, 0), Position(0, 1), board) is False

    def test_diagonal_onto_friendly_is_still_legal_pattern(self):
        """Friendly-fire is RuleEngine's generic job, not the piece
        rule's — the pattern itself (diagonal onto an occupied square)
        is legal regardless of colour."""
        board = _b(". wN", "wP .")
        assert self.rule.is_legal_move("wP", Position(1, 0), Position(0, 1), board) is True

    # -- two-step advance ------------------------------------------------

    def test_white_two_step_from_start_row_is_legal(self):
        board = _b(". .", ". .", "wP .", ". .")  # 4 rows: start row = 2
        assert self.rule.is_legal_move("wP", Position(2, 0), Position(0, 0), board) is True

    def test_white_two_step_off_start_row_is_illegal(self):
        board = _b(". .", ". .", ". .", "wP .")
        assert self.rule.is_legal_move("wP", Position(3, 0), Position(1, 0), board) is False

    def test_black_two_step_from_start_row_is_legal(self):
        board = _b(". .", "bP .", ". .", ". .")  # start row = 1
        assert self.rule.is_legal_move("bP", Position(1, 0), Position(3, 0), board) is True

    def test_two_step_onto_occupied_destination_is_illegal(self):
        board = _b("bN .", ". .", "wP .", ". .")
        assert self.rule.is_legal_move("wP", Position(2, 0), Position(0, 0), board) is False

    def test_three_steps_is_illegal(self):
        board = _b(". .", ". .", ". .", "wP .")
        assert self.rule.is_legal_move("wP", Position(3, 0), Position(0, 0), board) is False

    def test_requires_path_check_only_for_two_step(self):
        assert self.rule.requires_path_check(Position(3, 0), Position(1, 0)) is True
        assert self.rule.requires_path_check(Position(1, 0), Position(0, 0)) is False
        assert self.rule.requires_path_check(Position(1, 0), Position(0, 1)) is False


# ===========================================================================
# RuleEngine — every MoveResult branch
# ===========================================================================

class TestRuleEngineOutsideBoard:
    def setup_method(self):
        self.engine = RuleEngine()

    def test_to_pos_outside_board(self):
        board = _b("wR . .")
        result = self.engine.validate_move("wR", Position(0, 0), Position(0, 99), board)
        assert result == MoveResult.OUTSIDE_BOARD

    def test_from_pos_outside_board(self):
        board = _b("wR . .")
        result = self.engine.validate_move("wR", Position(5, 5), Position(0, 0), board)
        assert result == MoveResult.OUTSIDE_BOARD

    def test_negative_position_outside_board(self):
        board = _b("wR . .")
        result = self.engine.validate_move("wR", Position(0, 0), Position(-1, 0), board)
        assert result == MoveResult.OUTSIDE_BOARD


class TestRuleEngineSamePosition:
    def test_same_position_is_reported_even_with_a_piece_there(self):
        board = _b("wR . .")
        engine = RuleEngine()
        result = engine.validate_move("wR", Position(0, 0), Position(0, 0), board)
        assert result == MoveResult.SAME_POSITION


class TestRuleEngineEmptySource:
    def test_empty_source_cell(self):
        board = _b(". . .")
        engine = RuleEngine()
        result = engine.validate_move("wR", Position(0, 0), Position(0, 1), board)
        assert result == MoveResult.EMPTY_SOURCE


class TestRuleEngineUnknownPieceType:
    def test_unregistered_piece_type(self):
        board = _b("wX .")
        engine = RuleEngine()
        result = engine.validate_move("wX", Position(0, 0), Position(0, 1), board)
        assert result == MoveResult.UNKNOWN_PIECE_TYPE


class TestRuleEngineIllegalPattern:
    def test_rook_diagonal_is_illegal_pattern(self):
        board = _b("wR . .", ". . .", ". . .")
        engine = RuleEngine()
        result = engine.validate_move("wR", Position(0, 0), Position(2, 2), board)
        assert result == MoveResult.ILLEGAL_PATTERN

    def test_knight_straight_line_is_illegal_pattern(self):
        board = _b("wN . .")
        engine = RuleEngine()
        result = engine.validate_move("wN", Position(0, 0), Position(0, 2), board)
        assert result == MoveResult.ILLEGAL_PATTERN


class TestRuleEngineFriendlyFire:
    def test_landing_on_own_colour_is_friendly_fire(self):
        board = _b("wR wN .")
        engine = RuleEngine()
        result = engine.validate_move("wR", Position(0, 0), Position(0, 1), board)
        assert result == MoveResult.FRIENDLY_FIRE

    def test_friendly_fire_reported_even_though_pattern_was_legal(self):
        """Pattern legality is checked before friendly-fire — this test
        confirms a friendly destination doesn't masquerade as
        ILLEGAL_PATTERN; it gets its own, more specific result."""
        board = _b("wB . .", ". wN .", ". . .")
        engine = RuleEngine()
        result = engine.validate_move("wB", Position(0, 0), Position(1, 1), board)
        assert result == MoveResult.FRIENDLY_FIRE


class TestRuleEngineBlockedPath:
    def test_rook_blocked_by_intermediate_piece(self):
        board = _b("wR bN . .")
        engine = RuleEngine()
        result = engine.validate_move("wR", Position(0, 0), Position(0, 3), board)
        assert result == MoveResult.BLOCKED_PATH

    def test_bishop_blocked_by_intermediate_piece(self):
        board = _b("wB . . .", ". bN . .", ". . . .", ". . . .")
        engine = RuleEngine()
        result = engine.validate_move("wB", Position(0, 0), Position(2, 2), board)
        assert result == MoveResult.BLOCKED_PATH

    def test_pawn_two_step_blocked_by_intermediate_piece(self):
        board = _b(". .", "bN .", "wP .", ". .")  # blocker at the intermediate row
        engine = RuleEngine()
        result = engine.validate_move("wP", Position(2, 0), Position(0, 0), board)
        assert result == MoveResult.BLOCKED_PATH

    def test_knight_is_never_blocked(self):
        board = _b("wN bN .", ". . .")
        engine = RuleEngine()
        # (0,0) -> (1,2) is a legal knight L-shape jumping "over" bN at (0,1)
        result = engine.validate_move("wN", Position(0, 0), Position(1, 2), board)
        assert result == MoveResult.OK


class TestRuleEngineOk:
    def setup_method(self):
        self.engine = RuleEngine()

    def test_clear_rook_move_is_ok(self):
        board = _b("wR . .")
        assert self.engine.validate_move("wR", Position(0, 0), Position(0, 2), board) == MoveResult.OK

    def test_clear_bishop_move_is_ok(self):
        board = _b("wB . .", ". . .", ". . .")
        assert self.engine.validate_move("wB", Position(0, 0), Position(2, 2), board) == MoveResult.OK

    def test_clear_queen_diagonal_move_is_ok(self):
        board = _b("wQ . .", ". . .", ". . .")
        assert self.engine.validate_move("wQ", Position(0, 0), Position(2, 2), board) == MoveResult.OK

    def test_knight_jump_is_ok(self):
        board = _b("wN . .", ". . .", ". . .")
        assert self.engine.validate_move("wN", Position(0, 0), Position(1, 2), board) == MoveResult.OK

    def test_king_one_step_is_ok(self):
        board = _b(". . .", ". wK .", ". . .")
        assert self.engine.validate_move("wK", Position(1, 1), Position(1, 2), board) == MoveResult.OK

    def test_pawn_capture_is_ok(self):
        board = _b(". bN", "wP .")
        assert self.engine.validate_move("wP", Position(1, 0), Position(0, 1), board) == MoveResult.OK

    def test_enemy_capture_orthogonal_is_ok(self):
        board = _b("wR bN .")
        assert self.engine.validate_move("wR", Position(0, 0), Position(0, 1), board) == MoveResult.OK


# ===========================================================================
# RuleEngine.register — OCP extension point
# ===========================================================================

class TestRuleEngineRegister:
    def test_register_new_piece_type(self):
        engine = RuleEngine()
        engine.register("X", KnightRule())
        board = _b(". . . . .", ". . . . .", ". . wX . .", ". . . . .", ". . . . .")
        result = engine.validate_move("wX", Position(2, 2), Position(0, 1), board)
        assert result == MoveResult.OK

    def test_replace_existing_rule(self):
        class _AlwaysIllegal(IPieceRule):
            def is_legal_move(self, piece, from_pos, to_pos, board) -> bool:
                return False

        engine = RuleEngine()
        engine.register("R", _AlwaysIllegal())
        board = _b("wR . . .")
        result = engine.validate_move("wR", Position(0, 0), Position(0, 3), board)
        assert result == MoveResult.ILLEGAL_PATTERN

    def test_default_registry_is_not_mutated_by_instance(self):
        e1, e2 = RuleEngine(), RuleEngine()
        e1.register("R", KnightRule())
        board = _b("wR . . .")
        # e2's Rook must still behave like a real Rook.
        assert e2.validate_move("wR", Position(0, 0), Position(0, 3), board) == MoveResult.OK

    def test_custom_rule_can_return_illegal_pattern_for_everything(self):
        class _NeverLegal(IPieceRule):
            def is_legal_move(self, piece, from_pos, to_pos, board) -> bool:
                return False

        engine = RuleEngine(rules={"P": _NeverLegal()})
        board = _b(". .", "wP .")
        result = engine.validate_move("wP", Position(1, 0), Position(0, 0), board)
        assert result == MoveResult.ILLEGAL_PATTERN
