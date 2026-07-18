"""
Unit tests for ``MoveHistoryTracker`` (Kungfu Chess).

Every test here drives a real ``GameEngine`` through an actual move
(rather than hand-building ``GameSnapshot``s) so the diffing logic is
proven against what the engine genuinely produces, not an assumption
about its shape — same reasoning ``test_score_tracker.py`` gives for its
own tests, and the same engine mechanics (``GameEngine._resolve_due_move``)
both trackers diff against.

Covers the three things this feature's own task asked for:
  * a move is recorded exactly once when it completes,
  * a move that gets interrupted (never lands) is NOT recorded, and
  * pawn promotion is correctly recorded as a completed move (with
    ``kind="Q"``, not "P" — see CompletedMove's own docstring for why).
Plus the two additional "never lands" cases score_tracker.py's own tests
already established are real, distinct branches of
``_resolve_due_move`` (dropped as invalid, friendly-block stop-short),
and the chronological-ordering guarantee for several moves completing
within the same tick.
"""

from __future__ import annotations

from core.models import Color, Position
from engine.board import TextBoard
from engine.game import GameEngine
from engine.game_state import GameState
from engine.move_history_tracker import MoveHistoryTracker
from engine.snapshot import GameSnapshot


def _snap(state: GameState) -> GameSnapshot:
    return GameSnapshot.from_state(state)


class TestMoveHistoryTrackerBasics:
    def test_starts_empty(self):
        tracker = MoveHistoryTracker()
        assert tracker.moves == []

    def test_first_update_establishes_a_baseline_without_recording(self):
        board = TextBoard(["wR . ."])
        state = GameState(board=board)
        tracker = MoveHistoryTracker()
        tracker.update(_snap(state))
        assert tracker.moves == []


class TestACompletedMoveIsRecordedExactlyOnce:
    def test_a_landed_move_is_recorded(self):
        board = TextBoard(["wR . ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        tracker = MoveHistoryTracker()

        tracker.update(_snap(state))
        engine.attempt_move(state, Position(0, 0), Position(0, 2))
        tracker.update(_snap(state))  # still in transit -- not recorded yet
        assert tracker.moves == []

        engine.tick(state, 1000)  # arrives
        tracker.update(_snap(state))

        assert len(tracker.moves) == 1
        move = tracker.moves[0]
        assert move.color is Color.WHITE
        assert move.kind == "R"
        assert move.destination == Position(0, 2)
        assert move.time == 1000  # the move's own arrival_time

    def test_repeated_updates_on_an_unchanged_state_do_not_re_record(self):
        board = TextBoard(["wR . ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        tracker = MoveHistoryTracker()

        tracker.update(_snap(state))
        engine.attempt_move(state, Position(0, 0), Position(0, 2))
        tracker.update(_snap(state))  # captures it as pending
        engine.tick(state, 1000)
        tracker.update(_snap(state))
        assert len(tracker.moves) == 1

        tracker.update(_snap(state))
        tracker.update(_snap(state))
        assert len(tracker.moves) == 1

    def test_two_separate_moves_are_each_recorded_once(self):
        board = TextBoard(["wR . ."])
        # cooldown_duration=0 so the piece is selectable again immediately
        # after landing -- this test is about two distinct moves each
        # being recorded, not about cooldown timing.
        engine = GameEngine(board, cell_size=100, move_duration=500, cooldown_duration=0)
        state = GameState(board=board)
        tracker = MoveHistoryTracker()

        tracker.update(_snap(state))
        engine.attempt_move(state, Position(0, 0), Position(0, 1))
        tracker.update(_snap(state))
        engine.tick(state, 500)
        tracker.update(_snap(state))

        engine.attempt_move(state, Position(0, 1), Position(0, 2))
        tracker.update(_snap(state))
        engine.tick(state, 500)
        tracker.update(_snap(state))

        assert len(tracker.moves) == 2
        assert tracker.moves[0].destination == Position(0, 1)
        assert tracker.moves[1].destination == Position(0, 2)

    def test_several_moves_completing_in_the_same_tick_are_all_recorded_in_order(self):
        """Uses two different move_durations so the moves have distinct
        arrival_times despite resolving in the same tick() call --
        verifies they're recorded in chronological (arrival_time) order,
        not whatever order an unordered set diff happens to produce."""
        board = TextBoard(["wR . .", ". . .", ". wR .", ". . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        tracker = MoveHistoryTracker()

        tracker.update(_snap(state))
        engine.attempt_move(state, Position(0, 0), Position(0, 2))  # arrival_time=2000
        engine.attempt_move(state, Position(2, 1), Position(2, 0))  # arrival_time=1000
        tracker.update(_snap(state))
        engine.tick(state, 2000)
        tracker.update(_snap(state))

        assert [m.time for m in tracker.moves] == [1000, 2000]
        assert tracker.moves[0].destination == Position(2, 0)
        assert tracker.moves[1].destination == Position(0, 2)


class TestInterruptedMovesAreNotRecorded:
    def test_airborne_interception_is_not_recorded(self):
        """Mirrors tests/unit/test_jump.py::TestAirborneCapture's own
        board/click sequence -- the attacker is deleted outright and
        never reaches its destination."""
        board = TextBoard([". . .", "wK bR .", ". . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000, jump_duration=1000)
        state = GameState(board=board)
        tracker = MoveHistoryTracker()

        tracker.update(_snap(state))
        engine.handle_jump(state, 50, 150)     # wK airborne at (1, 0)
        engine.handle_click(state, 150, 150)   # select bR
        engine.handle_click(state, 50, 150)    # queue bR -> (1, 0), attacking wK
        tracker.update(_snap(state))
        engine.tick(state, 1000)  # bR deleted outright; wK never moves
        tracker.update(_snap(state))

        assert tracker.moves == []

    def test_friendly_block_stop_short_is_not_recorded(self):
        """The mover ends up somewhere other than its original
        destination -- not the move that was queued completing."""
        board = TextBoard(["wR . . . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        tracker = MoveHistoryTracker()

        tracker.update(_snap(state))
        engine.attempt_move(state, Position(0, 0), Position(0, 4))  # wR -> (0,4), 4000ms
        state.board.set_piece_at(Position(0, 2), "wN")  # a friendly appears mid-route
        tracker.update(_snap(state))
        engine.tick(state, 4000)  # stops short at (0,1)
        tracker.update(_snap(state))

        assert state.board.get_piece_at(Position(0, 1)) == "wR"
        assert tracker.moves == []

    def test_a_move_dropped_as_invalid_is_not_recorded(self):
        """The origin piece was captured elsewhere before this move's
        own turn to resolve came up -- _resolve_due_move's very first
        check (``state.board.get_piece_at(pm.from_pos) != pm.piece``)
        drops it silently, before MoveValidator is even consulted."""
        board = TextBoard(["wP . .", "bR . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        tracker = MoveHistoryTracker()

        tracker.update(_snap(state))
        engine.attempt_move(state, Position(0, 0), Position(0, 1))  # wP -> (0,1), slow
        # A faster enemy captures wP at its own origin before its move resolves.
        engine.try_move(state, Position(1, 0), Position(0, 0))
        tracker.update(_snap(state))
        engine.tick(state, 1000)
        tracker.update(_snap(state))

        assert state.board.get_piece_at(Position(0, 1)) == "."
        assert tracker.moves == []


class TestPawnPromotionIsRecordedAsCompleted:
    def test_promotion_is_recorded_with_kind_q(self):
        board = TextBoard([". . .", "wP . .", ". . ."])
        engine = GameEngine(board, cell_size=100, move_duration=100)
        state = GameState(board=board)
        tracker = MoveHistoryTracker()

        tracker.update(_snap(state))
        engine.attempt_move(state, Position(1, 0), Position(0, 0))
        tracker.update(_snap(state))
        engine.tick(state, 100)  # arrives at row 0 -> promotes to wQ
        assert state.board.get_piece_at(Position(0, 0)) == "wQ"

        tracker.update(_snap(state))

        assert len(tracker.moves) == 1
        move = tracker.moves[0]
        assert move.color is Color.WHITE
        assert move.kind == "Q"
        assert move.destination == Position(0, 0)

    def test_a_non_promoting_pawn_move_keeps_kind_p(self):
        # White advances toward decreasing row (see engine.geometry's
        # pawn_direction) -- row 2 -> row 1 is a legal single step that
        # doesn't yet reach the back rank (row 0), so no promotion.
        board = TextBoard([". . .", ". . .", "wP . ."])
        engine = GameEngine(board, cell_size=100, move_duration=100)
        state = GameState(board=board)
        tracker = MoveHistoryTracker()

        tracker.update(_snap(state))
        engine.attempt_move(state, Position(2, 0), Position(1, 0))
        tracker.update(_snap(state))
        engine.tick(state, 100)
        tracker.update(_snap(state))

        assert len(tracker.moves) == 1
        assert tracker.moves[0].kind == "P"
