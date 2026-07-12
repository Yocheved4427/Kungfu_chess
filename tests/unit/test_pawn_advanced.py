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

from core.models import Position
from engine.board import TextBoard
from engine.game import GameEngine


# ===========================================================================
# Two-step advance, queued and executed through the engine
# ===========================================================================

class TestTwoStepAdvanceViaEngine:
    def test_white_two_step_from_start_row_is_queued_and_executes(self):
        # 5 rows: White's start row (the edge it advances away from) is
        # num_rows - 1 = 4; lands on row 2, which is NOT the back rank
        # (row 0) — isolated from promotion. handle_click now applies
        # instantly via try_move — no queueing/ticking needed.
        board = TextBoard([". .", ". .", ". .", ". .", "wP ."])
        engine = GameEngine(board, cell_size=100)
        engine.handle_click(0, 400)  # select wP at (4,0)
        engine.handle_click(0, 200)  # two-step to (2,0) — applies now
        assert engine.board.get_piece_at(Position(2, 0)) == "wP"
        assert engine.board.get_piece_at(Position(4, 0)) == "."

    def test_black_two_step_from_start_row_is_queued_and_executes(self):
        # 5 rows: Black's start row is always 0; lands on row 2, which is
        # NOT the back rank (row num_rows-1 = 4) — isolated from promotion.
        board = TextBoard(["bP .", ". .", ". .", ". .", ". ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        engine.handle_click(0, 0)    # select bP at (0,0)
        engine.handle_click(0, 200)  # two-step to (2,0)
        engine.tick(1000)
        assert engine.board.get_piece_at(Position(2, 0)) == "bP"

    def test_two_step_off_start_row_is_not_queued(self):
        # 4 rows: White's start row = 3; pawn sits at 2, one off it.
        board = TextBoard([". .", ". .", "wP .", ". ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        engine.handle_click(0, 200)  # select wP at (2,0)
        engine.handle_click(0, 0)    # attempt two-step to (0,0) — off start row
        assert engine._pending == []
        assert engine.selection is None

    def test_two_step_blocked_by_intermediate_piece_is_not_queued(self):
        board = TextBoard([". .", ". .", "bN .", "wP ."])  # wP on start row = 3
        engine = GameEngine(board, cell_size=100, move_duration=500)
        engine.handle_click(0, 300)  # select wP at (3,0)
        engine.handle_click(0, 100)  # attempt two-step through blocked (2,0)
        assert engine._pending == []

    def test_two_step_path_becomes_blocked_before_arrival_is_dropped(self):
        """Legal when queued (path clear), but a piece lands in the
        intermediate square before arrival — the premove must be dropped,
        same as any other sliding-style premove (see
        test_realtime_conflicts.py::TestInvalidPremoves).

        This re-validate-at-arrival behaviour is specific to the queued
        attempt_move/tick() pipeline (try_move applies instantly, so
        there's no "premove" window for anything to invalidate) — both
        moves are driven via attempt_move directly."""
        board = TextBoard([". . .", ". . .", ". bK .", "wP . ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        engine.attempt_move(Position(3, 0), Position(1, 0))  # two-step, path clear now
        engine.attempt_move(Position(2, 1), Position(2, 0))  # bK, 1 cell, arrives first
        engine.tick(1000)
        assert engine.board.get_piece_at(Position(3, 0)) == "wP"  # never moved
        assert engine.board.get_piece_at(Position(2, 0)) == "bK"
        assert engine.board.get_piece_at(Position(1, 0)) == "."

    def test_one_step_move_still_works_after_two_step_feature_added(self):
        # wP moves from the bottom row to the middle row — not the back
        # rank (row 0) — isolated from promotion.
        board = TextBoard([". .", ". .", "wP ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        engine.handle_click(0, 200)  # select wP at (2,0)
        engine.handle_click(0, 100)  # one-step to (1,0)
        engine.tick(500)
        assert engine.board.get_piece_at(Position(1, 0)) == "wP"


# ===========================================================================
# Promotion
# ===========================================================================

class TestPromotion:
    def test_white_pawn_reaching_row_zero_promotes_to_queen(self):
        board = TextBoard([". .", "wP ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        engine.handle_click(0, 100)  # select wP at (1,0)
        engine.handle_click(0, 0)    # forward to (0,0) — the back rank
        engine.tick(500)
        assert engine.board.get_piece_at(Position(0, 0)) == "wQ"

    def test_black_pawn_reaching_last_row_promotes_to_queen(self):
        board = TextBoard(["bP .", ". ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        engine.handle_click(0, 0)    # select bP at (0,0)
        engine.handle_click(0, 100)  # forward to (1,0) — the back rank
        engine.tick(500)
        assert engine.board.get_piece_at(Position(1, 0)) == "bQ"

    def test_promotion_via_diagonal_capture(self):
        """Promotion applies regardless of how the pawn arrives — a
        capturing diagonal move onto the back rank promotes too."""
        board = TextBoard(["bN bN", "wP ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        engine.handle_click(0, 100)    # select wP at (1,0)
        engine.handle_click(100, 0)    # diagonal capture bN at (0,1)
        engine.tick(500)
        assert engine.board.get_piece_at(Position(0, 1)) == "wQ"

    def test_promoted_queen_moves_like_a_queen_immediately(self):
        """No cooldown: the very next click can move the new Queen using
        Queen rules (e.g. a long diagonal a Pawn could never make).
        handle_click applies instantly now, so promotion and the
        follow-up move both happen without any tick()."""
        board = TextBoard([". . .", "wP . .", ". . ."])
        engine = GameEngine(board, cell_size=100)
        engine.handle_click(0, 100)    # select wP at (1,0)
        engine.handle_click(0, 0)      # forward to (0,0) — promotes to wQ now
        assert engine.board.get_piece_at(Position(0, 0)) == "wQ"
        engine.handle_click(0, 0)      # select the new wQ
        engine.handle_click(200, 200)  # long diagonal — legal for a Queen, applies now
        assert engine.board.get_piece_at(Position(2, 2)) == "wQ"
        assert engine.board.get_piece_at(Position(0, 0)) == "."

    def test_non_back_rank_arrival_does_not_promote(self):
        board = TextBoard([". .", ". .", "wP ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        engine.handle_click(0, 200)  # select wP at (2,0)
        engine.handle_click(0, 100)  # forward to (1,0) — not the back rank
        engine.tick(500)
        assert engine.board.get_piece_at(Position(1, 0)) == "wP"

    def test_non_pawn_reaching_last_row_is_not_promoted(self):
        board = TextBoard([". .", "wR ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        engine.handle_click(0, 100)  # select wR at (1,0)
        engine.handle_click(0, 0)    # forward to (0,0)
        engine.tick(500)
        assert engine.board.get_piece_at(Position(0, 0)) == "wR"

    def test_promotion_fires_the_normal_move_completed_event_for_the_pawn(self):
        from ui.events import GameEvent, MoveCompletedEvent, Observer

        class _Recorder(Observer):
            def __init__(self) -> None:
                self.events: list[GameEvent] = []

            def on_event(self, event: GameEvent) -> None:
                self.events.append(event)

        board = TextBoard([". .", "wP ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        obs = _Recorder()
        engine.add_observer(obs)
        engine.handle_click(0, 100)
        engine.handle_click(0, 0)
        engine.tick(500)
        completed = [e for e in obs.events if isinstance(e, MoveCompletedEvent)]
        assert len(completed) == 1
        assert completed[0].piece == "wP"  # event reports the pre-promotion piece
        assert engine.board.get_piece_at(Position(0, 0)) == "wQ"
