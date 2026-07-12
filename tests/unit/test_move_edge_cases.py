"""
Explicit unit tests for invalid / edge-case move inputs, across both
RuleEngine (engine/rule_engine.py) and GameEngine (engine/game.py).

Five categories, per the spec:
  1. Moves outside the board.
  2. Moving from an empty cell.
  3. Illegal movement patterns, one case per piece type.
  4. Blocked paths, one case per sliding piece (+ Pawn's two-step).
  5. Attempts to move after the king has already been captured.

Every assertion checks the EXACT result — the specific MoveResult enum
member for RuleEngine.validate_move()/GameEngine.try_move(), or the
precise False/no-op/unchanged-state contract for GameEngine.attempt_move()
/handle_click()/handle_jump() — never just a bare pass/fail.

Coverage that already lives elsewhere is not duplicated wholesale here:
  * Per-piece IPieceRule.is_legal_move()/requires_path_check() unit
    tests: test_rule_engine.py (TestRookRule, TestBishopRule, ...).
  * RuleEngine.validate_move()'s core dispatch (one case per branch,
    Rook/Knight only): test_rule_engine.py.
  * KingCaptureRule / GameOverRule semantics: test_game_over.py.
This file's job is breadth per piece type and GameEngine-level breadth
across all the pathways a caller can use to attempt a move.
"""

from __future__ import annotations

from core.models import Position
from engine.board import TextBoard
from engine.game import GameEngine
from engine.rule_engine import MoveResult, RuleEngine


def _b(*rows: str) -> TextBoard:
    return TextBoard(list(rows))


# ===========================================================================
# 1. Moves outside the board
# ===========================================================================

class TestOutsideBoardRuleEngine:
    def setup_method(self):
        self.engine = RuleEngine()

    def test_to_pos_column_past_the_right_edge(self):
        board = _b("wR . .")
        result = self.engine.validate_move("wR", Position(0, 0), Position(0, 3), board)
        assert result == MoveResult.OUTSIDE_BOARD

    def test_to_pos_row_past_the_bottom_edge(self):
        board = _b("wR . .", ". . .", ". . .")
        result = self.engine.validate_move("wR", Position(0, 0), Position(3, 0), board)
        assert result == MoveResult.OUTSIDE_BOARD

    def test_to_pos_negative_row(self):
        board = _b("wR . .", ". . .")
        result = self.engine.validate_move("wR", Position(1, 0), Position(-1, 0), board)
        assert result == MoveResult.OUTSIDE_BOARD

    def test_to_pos_negative_column(self):
        board = _b("wR . .")
        result = self.engine.validate_move("wR", Position(0, 1), Position(0, -1), board)
        assert result == MoveResult.OUTSIDE_BOARD

    def test_from_pos_outside_board(self):
        board = _b("wR . .")
        result = self.engine.validate_move("wR", Position(9, 9), Position(0, 0), board)
        assert result == MoveResult.OUTSIDE_BOARD

    def test_both_positions_outside_board(self):
        board = _b("wR . .")
        result = self.engine.validate_move("wR", Position(50, 50), Position(-3, -3), board)
        assert result == MoveResult.OUTSIDE_BOARD

    def test_outside_board_takes_priority_over_unknown_piece_type(self):
        """Bounds are checked before anything about the piece itself —
        an out-of-bounds move with a nonsense piece type is still
        reported as OUTSIDE_BOARD, not UNKNOWN_PIECE_TYPE."""
        board = _b("wZ .")
        result = self.engine.validate_move("wZ", Position(0, 0), Position(0, 99), board)
        assert result == MoveResult.OUTSIDE_BOARD


class TestOutsideBoardGameEngine:
    def test_attempt_move_to_pos_outside_board_returns_false(self):
        board = _b("wR . .")
        engine = GameEngine(board, move_duration=1000)
        assert engine.attempt_move(Position(0, 0), Position(0, 99)) is False
        assert engine._pending == []

    def test_try_move_to_pos_outside_board_returns_outside_board(self):
        board = _b("wR . .")
        engine = GameEngine(board)
        assert engine.try_move(Position(0, 0), Position(0, 99)) == MoveResult.OUTSIDE_BOARD
        assert board.get_piece_at(Position(0, 0)) == "wR"

    def test_click_outside_board_is_silently_ignored(self):
        board = _b("wK . .")
        engine = GameEngine(board, cell_size=100)
        engine.handle_click(9999, 9999)
        assert engine.selection is None

    def test_click_negative_pixel_is_silently_ignored(self):
        board = _b("wK . .")
        engine = GameEngine(board, cell_size=100)
        engine.handle_click(-50, -50)
        assert engine.selection is None


# ===========================================================================
# 2. Moving from an empty cell
# ===========================================================================

class TestEmptySourceRuleEngine:
    def setup_method(self):
        self.engine = RuleEngine()

    def test_empty_source_reports_empty_source(self):
        board = _b(". . .")
        result = self.engine.validate_move("wR", Position(0, 0), Position(0, 1), board)
        assert result == MoveResult.EMPTY_SOURCE

    def test_empty_source_regardless_of_claimed_piece_type(self):
        """The claimed *piece* string is irrelevant once the board says
        from_pos is empty — EMPTY_SOURCE wins before the piece registry
        is even consulted."""
        board = _b(". . .")
        result = self.engine.validate_move("bQ", Position(0, 0), Position(0, 1), board)
        assert result == MoveResult.EMPTY_SOURCE

    def test_empty_source_at_a_non_origin_cell(self):
        board = _b("wR . .", ". . .", ". . .")
        result = self.engine.validate_move("wR", Position(1, 1), Position(1, 2), board)
        assert result == MoveResult.EMPTY_SOURCE

    def test_empty_source_takes_priority_over_unknown_piece_type(self):
        board = _b(". .")
        result = self.engine.validate_move("wZ", Position(0, 0), Position(0, 1), board)
        assert result == MoveResult.EMPTY_SOURCE


class TestEmptySourceGameEngine:
    def test_attempt_move_from_empty_cell_returns_false(self):
        engine = GameEngine(_b(". . ."), move_duration=1000)
        assert engine.attempt_move(Position(0, 0), Position(0, 1)) is False
        assert engine._pending == []

    def test_try_move_from_empty_cell_returns_empty_source(self):
        engine = GameEngine(_b(". . ."))
        assert engine.try_move(Position(0, 0), Position(0, 1)) == MoveResult.EMPTY_SOURCE

    def test_click_on_empty_cell_does_not_select(self):
        engine = GameEngine(_b(". . ."), cell_size=100)
        engine.handle_click(0, 0)
        assert engine.selection is None


# ===========================================================================
# 3. Illegal movement patterns — one case per piece type
# ===========================================================================

class TestIllegalPatternPerPiece:
    def setup_method(self):
        self.engine = RuleEngine()

    def test_rook_diagonal_move_is_illegal(self):
        board = _b("wR . .", ". . .", ". . .")
        result = self.engine.validate_move("wR", Position(0, 0), Position(2, 2), board)
        assert result == MoveResult.ILLEGAL_PATTERN

    def test_bishop_orthogonal_move_is_illegal(self):
        board = _b("wB . .")
        result = self.engine.validate_move("wB", Position(0, 0), Position(0, 2), board)
        assert result == MoveResult.ILLEGAL_PATTERN

    def test_bishop_uneven_diagonal_is_illegal(self):
        board = _b("wB . .", ". . .")
        result = self.engine.validate_move("wB", Position(0, 0), Position(1, 2), board)
        assert result == MoveResult.ILLEGAL_PATTERN

    def test_knight_straight_line_is_illegal(self):
        board = _b("wN . .")
        result = self.engine.validate_move("wN", Position(0, 0), Position(0, 2), board)
        assert result == MoveResult.ILLEGAL_PATTERN

    def test_knight_diagonal_is_illegal(self):
        board = _b("wN . .", ". . .")
        result = self.engine.validate_move("wN", Position(0, 0), Position(1, 1), board)
        assert result == MoveResult.ILLEGAL_PATTERN

    def test_queen_knight_shape_is_illegal(self):
        board = _b("wQ . .", ". . .")
        result = self.engine.validate_move("wQ", Position(0, 0), Position(1, 2), board)
        assert result == MoveResult.ILLEGAL_PATTERN

    def test_king_two_steps_is_illegal(self):
        board = _b("wK . .")
        result = self.engine.validate_move("wK", Position(0, 0), Position(0, 2), board)
        assert result == MoveResult.ILLEGAL_PATTERN

    def test_king_knight_shape_is_illegal(self):
        board = _b("wK . .", ". . .")
        result = self.engine.validate_move("wK", Position(0, 0), Position(1, 2), board)
        assert result == MoveResult.ILLEGAL_PATTERN

    def test_pawn_sideways_move_is_illegal(self):
        board = _b("wP . .")
        result = self.engine.validate_move("wP", Position(0, 0), Position(0, 1), board)
        assert result == MoveResult.ILLEGAL_PATTERN

    def test_pawn_backward_move_is_illegal(self):
        board = _b("wP .", ". .")
        result = self.engine.validate_move("wP", Position(0, 0), Position(1, 0), board)
        assert result == MoveResult.ILLEGAL_PATTERN

    def test_pawn_three_step_is_illegal(self):
        board = _b(". .", ". .", ". .", "wP .")
        result = self.engine.validate_move("wP", Position(3, 0), Position(0, 0), board)
        assert result == MoveResult.ILLEGAL_PATTERN


class TestIllegalPatternGameEngine:
    def test_attempt_move_illegal_pattern_returns_false(self):
        board = _b("wB . .")
        engine = GameEngine(board, move_duration=1000)
        assert engine.attempt_move(Position(0, 0), Position(0, 1)) is False
        assert engine._pending == []

    def test_try_move_illegal_pattern_returns_illegal_pattern(self):
        board = _b("wB . .")
        engine = GameEngine(board)
        assert engine.try_move(Position(0, 0), Position(0, 1)) == MoveResult.ILLEGAL_PATTERN
        assert board.get_piece_at(Position(0, 0)) == "wB"

    def test_click_illegal_pattern_leaves_board_unchanged(self):
        board = _b("wN . .")
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        engine.handle_click(50, 50)    # select wN
        engine.handle_click(250, 50)   # straight line — illegal for a Knight
        assert engine._pending == []
        assert board.get_piece_at(Position(0, 0)) == "wN"


# ===========================================================================
# 4. Blocked paths — one case per sliding piece (+ Pawn's two-step)
# ===========================================================================

class TestBlockedPathPerPiece:
    def setup_method(self):
        self.engine = RuleEngine()

    def test_rook_blocked_horizontally(self):
        board = _b("wR bN . .")
        result = self.engine.validate_move("wR", Position(0, 0), Position(0, 3), board)
        assert result == MoveResult.BLOCKED_PATH

    def test_rook_blocked_vertically(self):
        board = _b("wR . .", "bN . .", ". . .")
        result = self.engine.validate_move("wR", Position(0, 0), Position(2, 0), board)
        assert result == MoveResult.BLOCKED_PATH

    def test_bishop_blocked_diagonally(self):
        board = _b("wB . . .", ". bN . .", ". . . .")
        result = self.engine.validate_move("wB", Position(0, 0), Position(2, 2), board)
        assert result == MoveResult.BLOCKED_PATH

    def test_queen_blocked_orthogonally(self):
        board = _b("wQ bN . .")
        result = self.engine.validate_move("wQ", Position(0, 0), Position(0, 3), board)
        assert result == MoveResult.BLOCKED_PATH

    def test_queen_blocked_diagonally(self):
        board = _b("wQ . . .", ". bN . .", ". . . .")
        result = self.engine.validate_move("wQ", Position(0, 0), Position(2, 2), board)
        assert result == MoveResult.BLOCKED_PATH

    def test_pawn_two_step_blocked_by_intermediate_piece(self):
        board = _b(". .", ". .", "bN .", "wP .")  # blocker on the intermediate row
        result = self.engine.validate_move("wP", Position(3, 0), Position(1, 0), board)
        assert result == MoveResult.BLOCKED_PATH

    def test_knight_is_never_blocked_by_an_intermediate_piece(self):
        board = _b("wN bN .", ". . .")
        result = self.engine.validate_move("wN", Position(0, 0), Position(1, 2), board)
        assert result == MoveResult.OK

    def test_king_one_step_has_no_intermediate_square_to_block(self):
        board = _b(". . .", ". wK .", ". . .")
        result = self.engine.validate_move("wK", Position(1, 1), Position(1, 2), board)
        assert result == MoveResult.OK


class TestBlockedPathGameEngine:
    def test_attempt_move_blocked_path_returns_false(self):
        board = _b("wR bN . .")
        engine = GameEngine(board, move_duration=1000)
        assert engine.attempt_move(Position(0, 0), Position(0, 3)) is False
        assert engine._pending == []

    def test_try_move_blocked_path_returns_blocked_path(self):
        board = _b("wR bN . .")
        engine = GameEngine(board)
        assert engine.try_move(Position(0, 0), Position(0, 3)) == MoveResult.BLOCKED_PATH
        assert board.get_piece_at(Position(0, 0)) == "wR"

    def test_click_blocked_path_leaves_board_unchanged(self):
        board = _b("wR bN . .")
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        engine.handle_click(50, 50)    # select wR
        engine.handle_click(350, 50)   # blocked by bN — illegal
        assert engine._pending == []
        assert board.get_piece_at(Position(0, 0)) == "wR"


# ===========================================================================
# 5. Attempts to move after the king has already been captured
# ===========================================================================

class TestMoveAfterKingCaptured:
    """Once GameEngine.game_over is True (a king was captured), every
    move pathway must refuse further moves — checked explicitly across
    handle_click, attempt_move, try_move, and handle_jump."""

    def _engine_with_game_over(self) -> GameEngine:
        board = _b("wR . .", "bK . .", ". . wN")
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        engine.attempt_move(Position(0, 0), Position(1, 0))  # captures bK
        engine.tick(1000)
        assert engine.game_over is True
        return engine

    def test_game_over_is_true_after_king_capture(self):
        engine = self._engine_with_game_over()
        assert engine.game_over is True
        assert engine.winner is not None

    def test_attempt_move_after_king_captured_returns_false(self):
        engine = self._engine_with_game_over()
        before = engine.board.get_rows()
        assert engine.attempt_move(Position(2, 2), Position(2, 1)) is False
        assert engine._pending == []
        assert engine.board.get_rows() == before

    def test_try_move_after_king_captured_returns_game_over(self):
        engine = self._engine_with_game_over()
        before = engine.board.get_rows()
        result = engine.try_move(Position(2, 2), Position(2, 1))
        assert result == MoveResult.GAME_OVER
        assert engine.board.get_rows() == before

    def test_try_move_game_over_short_circuits_before_rule_engine(self):
        """GAME_OVER is decided by GameEngine itself, before RuleEngine
        is even consulted — confirmed with a RuleEngine stub that would
        otherwise report OK for anything."""

        class _AlwaysOk(RuleEngine):
            def validate_move(self, *args, **kwargs) -> MoveResult:
                return MoveResult.OK

        board = _b("wR . .", "bK . .")
        engine = GameEngine(board, move_duration=1000, rule_engine=_AlwaysOk())
        engine.attempt_move(Position(0, 0), Position(1, 0))  # captures bK
        engine.tick(1000)
        assert engine.game_over is True
        assert engine.try_move(Position(1, 0), Position(1, 1)) == MoveResult.GAME_OVER

    def test_click_after_king_captured_does_not_select(self):
        engine = self._engine_with_game_over()
        engine.handle_click(250, 250)  # attempt to select wN
        assert engine.selection is None

    def test_click_after_king_captured_does_not_move(self):
        engine = self._engine_with_game_over()
        before = engine.board.get_rows()
        engine.handle_click(250, 250)  # select attempt — ignored
        engine.handle_click(150, 250)  # move attempt — ignored
        assert engine._pending == []
        assert engine.board.get_rows() == before

    def test_jump_after_king_captured_is_ignored(self):
        engine = self._engine_with_game_over()
        engine.handle_jump(250, 250)   # attempt to send wN airborne
        assert engine._airborne == []

    def test_legal_looking_move_after_king_captured_still_rejected(self):
        """Even a move that would otherwise be perfectly legal (a clear
        Knight jump) is refused once the game is over."""
        engine = self._engine_with_game_over()
        assert engine.attempt_move(Position(2, 2), Position(0, 1)) is False
        assert engine.try_move(Position(2, 2), Position(0, 1)) == MoveResult.GAME_OVER
