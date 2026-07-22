"""
Unit tests for advanced Pawn rules wired through GameEngine:

  1. A Pawn may move two cells forward from its start row.
  2. The path (the single intermediate square) must be clear.
  3. A Pawn that reaches the back rank is promoted to a Queen.

Rule-level coverage (PawnRule.is_valid_shape / is_valid_with_context /
requires_path_check / is_valid_with_board, and MoveValidator integration)
lives in test_rules.py. This file exercises the same features end-to-end
through handle_click()/tick(), including the promotion side effect that
only GameEngine performs (via AbstractBoard.set_piece_at).
"""

from __future__ import annotations

from core.models import Color, Position
from engine.board import TextBoard
from engine.game import GameEngine
from engine.game_state import GameState


# ===========================================================================
# Two-step advance, queued and executed through the engine
# ===========================================================================

class TestTwoStepAdvanceViaEngine:
    def test_white_two_step_from_start_row_is_queued_and_executes(self):
        # 5 rows: White's start row (one row in front of the back rank
        # it advances away from) is num_rows - 2 = 3; lands on row 1,
        # which is NOT the back rank (row 0) — isolated from promotion.
        board = TextBoard([". .", ". .", ". .", "wP .", ". ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        engine.handle_click(state, 0, 300)  # select wP at (3,0)
        engine.handle_click(state, 0, 100)  # two-step to (1,0)
        assert len(state.pending) == 1
        engine.tick(state, 1000)  # Chebyshev distance 2 * 500ms
        assert state.board.get_piece_at(Position(1, 0)) == "wP"
        assert state.board.get_piece_at(Position(3, 0)) == "."

    def test_black_two_step_from_start_row_is_queued_and_executes(self):
        # 5 rows: Black's start row is always 1; lands on row 3, which is
        # NOT the back rank (row num_rows-1 = 4) — isolated from promotion.
        board = TextBoard([". .", "bP .", ". .", ". .", ". ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        engine.handle_click(state, 0, 100)  # select bP at (1,0)
        engine.handle_click(state, 0, 300)  # two-step to (3,0)
        engine.tick(state, 1000)
        assert state.board.get_piece_at(Position(3, 0)) == "bP"

    def test_two_step_off_start_row_is_not_queued(self):
        # 4 rows: White's start row = 2; pawn sits at 3 (the back rank), one off it.
        board = TextBoard([". .", ". .", ". .", "wP ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        engine.handle_click(state, 0, 300)  # select wP at (3,0)
        engine.handle_click(state, 0, 100)  # attempt two-step to (1,0) — off start row
        assert state.pending == []
        assert engine.selection is None

    def test_two_step_blocked_by_intermediate_piece_is_not_queued(self):
        board = TextBoard([". .", "bN .", "wP .", ". ."])  # wP on start row = 2
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        engine.handle_click(state, 0, 200)  # select wP at (2,0)
        engine.handle_click(state, 0, 0)    # attempt two-step through blocked (1,0)
        assert state.pending == []

    def test_two_step_path_becomes_blocked_before_arrival_is_dropped(self):
        """Legal when queued (path clear), but a piece lands in the
        intermediate square before arrival — the premove must be dropped,
        same as any other sliding-style premove (see
        test_realtime_conflicts.py::TestInvalidPremoves)."""
        board = TextBoard([". . .", ". bK .", "wP . .", ". . ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        engine.handle_click(state, 0, 200)    # select wP at (2,0)
        engine.handle_click(state, 0, 0)      # queue two-step to (0,0), path clear now
        engine.handle_click(state, 100, 100)  # select bK at (1,1)
        engine.handle_click(state, 0, 100)    # queue bK -> (1,0), 1 cell, arrives first
        engine.tick(state, 1000)
        assert state.board.get_piece_at(Position(2, 0)) == "wP"  # never moved
        assert state.board.get_piece_at(Position(1, 0)) == "bK"
        assert state.board.get_piece_at(Position(0, 0)) == "."

    def test_one_step_move_still_works_after_two_step_feature_added(self):
        # wP moves from the bottom row to the middle row — not the back
        # rank (row 0) — isolated from promotion.
        board = TextBoard([". .", ". .", "wP ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        engine.handle_click(state, 0, 200)  # select wP at (2,0)
        engine.handle_click(state, 0, 100)  # one-step to (1,0)
        engine.tick(state, 500)
        assert state.board.get_piece_at(Position(1, 0)) == "wP"


# ===========================================================================
# Promotion
# ===========================================================================

class TestPromotion:
    def test_white_pawn_reaching_row_zero_promotes_to_queen(self):
        board = TextBoard([". .", "wP ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        engine.handle_click(state, 0, 100)  # select wP at (1,0)
        engine.handle_click(state, 0, 0)    # forward to (0,0) — the back rank
        engine.tick(state, 500)
        assert state.board.get_piece_at(Position(0, 0)) == "wQ"

    def test_black_pawn_reaching_last_row_promotes_to_queen(self):
        board = TextBoard(["bP .", ". ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        engine.handle_click(state, 0, 0)    # select bP at (0,0)
        engine.handle_click(state, 0, 100)  # forward to (1,0) — the back rank
        engine.tick(state, 500)
        assert state.board.get_piece_at(Position(1, 0)) == "bQ"

    def test_promotion_via_diagonal_capture(self):
        """Promotion applies regardless of how the pawn arrives — a
        capturing diagonal move onto the back rank promotes too."""
        board = TextBoard(["bN bN", "wP ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        engine.handle_click(state, 0, 100)    # select wP at (1,0)
        engine.handle_click(state, 100, 0)    # diagonal capture bN at (0,1)
        engine.tick(state, 500)
        assert state.board.get_piece_at(Position(0, 1)) == "wQ"

    def test_promoted_queen_moves_like_a_queen_once_cooldown_elapses(self):
        """Once the post-landing cooldown (see test_cooldown.py) elapses,
        the new Queen can be moved using Queen rules (e.g. a long diagonal
        a Pawn could never make) — promotion doesn't grant any special
        cooldown exemption or extra restriction."""
        board = TextBoard([". . .", "wP . .", ". . ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        engine.handle_click(state, 0, 100)    # select wP at (1,0)
        engine.handle_click(state, 0, 0)      # forward to (0,0), promotes to wQ
        engine.tick(state, 500)               # lands + promotes; cooldown until 1500
        assert state.board.get_piece_at(Position(0, 0)) == "wQ"
        engine.tick(state, 1000)              # clock = 1500, cooldown just elapsed
        engine.handle_click(state, 0, 0)      # select the new wQ
        engine.handle_click(state, 200, 200)  # long diagonal — legal for a Queen
        assert len(state.pending) == 1
        assert state.pending[0].piece == "wQ"

    def test_non_back_rank_arrival_does_not_promote(self):
        board = TextBoard([". .", ". .", "wP ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        engine.handle_click(state, 0, 200)  # select wP at (2,0)
        engine.handle_click(state, 0, 100)  # forward to (1,0) — not the back rank
        engine.tick(state, 500)
        assert state.board.get_piece_at(Position(1, 0)) == "wP"

    def test_non_pawn_reaching_last_row_is_not_promoted(self):
        board = TextBoard([". .", "wR ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        engine.handle_click(state, 0, 100)  # select wR at (1,0)
        engine.handle_click(state, 0, 0)    # forward to (0,0)
        engine.tick(state, 500)
        assert state.board.get_piece_at(Position(0, 0)) == "wR"

    def test_promotion_fires_the_normal_move_completed_event_for_the_pawn(self):
        from ui.events import GameEvent, MoveCompletedEvent, Observer

        class _Recorder(Observer):
            def __init__(self) -> None:
                self.events: list[GameEvent] = []

            def on_event(self, event: GameEvent) -> None:
                self.events.append(event)

        board = TextBoard([". .", "wP ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        obs = _Recorder()
        engine.add_observer(obs)
        engine.handle_click(state, 0, 100)
        engine.handle_click(state, 0, 0)
        engine.tick(state, 500)
        completed = [e for e in obs.events if isinstance(e, MoveCompletedEvent)]
        assert len(completed) == 1
        assert completed[0].piece == "wP"  # event reports the pre-promotion piece
        assert state.board.get_piece_at(Position(0, 0)) == "wQ"


# ===========================================================================
# Promotion vs. a simultaneous king-capture win
# ===========================================================================
#
# A pawn that captures the enemy King by landing on the back rank has
# already won the game in that same move -- promoting it to a Queen right
# afterward is meaningless (the game is over) and visually confusing (any
# game-over recap/animation would show a Queen instead of the pawn that
# actually delivered the winning capture). See TestGameOverEndsTheGame in
# test_game_over.py for the equivalent king-capture-only wiring this
# builds on.
# ===========================================================================

class TestPromotionSkippedWhenTheCaptureEndsTheGame:
    def test_pawn_capturing_the_king_on_the_back_rank_is_not_promoted(self):
        # wP at (1,1) diagonally captures bK at (0,0) -- lands on White's
        # back rank (row 0) in the very same move that wins the game.
        board = TextBoard(["bK .", ". wP"])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        engine.handle_click(state, 100, 100)  # select wP at (1,1)
        engine.handle_click(state, 0, 0)      # capture bK at (0,0)
        engine.tick(state, 500)
        assert state.board.get_piece_at(Position(0, 0)) == "wP"
        assert state.game_over is True
        assert state.winner is Color.WHITE

    def test_normal_promotion_without_a_king_capture_is_unaffected(self):
        """Regression guard: the skip above must not affect the ordinary
        promotion path when no king capture is involved."""
        board = TextBoard([". .", "wP ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        engine.handle_click(state, 0, 100)  # select wP at (1,0)
        engine.handle_click(state, 0, 0)    # forward to (0,0)
        engine.tick(state, 500)
        assert state.board.get_piece_at(Position(0, 0)) == "wQ"
        assert state.game_over is False
