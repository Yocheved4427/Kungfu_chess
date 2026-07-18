"""
Unit tests for ``ScoreTracker`` (Kungfu Chess).

Score is CUMULATIVE, based on captures (PIECE_POINTS), never a live
recount of remaining material, and never decreases. Every test here
drives a real ``GameEngine`` through an actual capture (rather than
hand-building ``GameSnapshot``s) so the diffing logic is proven against
what the engine genuinely produces, not an assumption about its shape —
same reasoning ``test_collision_resolver.py`` gives for leaving its own
class's real-pipeline coverage to test_realtime_conflicts.py/test_jump.py.

Covers both ways ``GameEngine._resolve_due_move`` actually produces a
capture (see that method's docstring, and score_tracker.py's own module
docstring for why both are needed):
  * an ordinary arrival landing on an enemy (overwrite), and
  * an airborne interception (``AirborneCaptureEvent``), where the
    arriving piece is deleted outright and the defender never moves.
Plus the specific false-positive this module's diffing has to guard
against: a piece captured at its own origin by something unrelated,
whose own now-stale queued destination happens to also hold an
unrelated airborne enemy.
"""

from __future__ import annotations

from core.config import PIECE_POINTS
from core.models import Color, Position
from engine.board import TextBoard
from engine.game import GameEngine
from engine.game_state import GameState
from engine.score_tracker import ScoreTracker
from engine.snapshot import GameSnapshot


def _snap(state: GameState) -> GameSnapshot:
    return GameSnapshot.from_state(state)


class TestScoreTrackerBasics:
    def test_both_scores_start_at_zero(self):
        tracker = ScoreTracker()
        assert tracker.get_score(Color.WHITE) == 0
        assert tracker.get_score(Color.BLACK) == 0

    def test_first_update_establishes_a_baseline_without_scoring(self):
        """Nothing to diff against yet — same idiom as a freshly-created
        PieceView's first sync()."""
        board = TextBoard(["wR . bN"])
        state = GameState(board=board)
        tracker = ScoreTracker()
        tracker.update(_snap(state))
        assert tracker.get_score(Color.WHITE) == 0
        assert tracker.get_score(Color.BLACK) == 0


class TestOverwriteCaptureScoring:
    def test_capturing_a_knight_scores_only_the_capturer(self):
        board = TextBoard(["wR . bN"])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        tracker = ScoreTracker()

        tracker.update(_snap(state))
        engine.attempt_move(state, Position(0, 0), Position(0, 2))
        tracker.update(_snap(state))  # still in transit -- no capture yet
        assert tracker.get_score(Color.WHITE) == 0

        engine.tick(state, 2000)  # arrives, captures bN
        tracker.update(_snap(state))

        assert tracker.get_score(Color.WHITE) == PIECE_POINTS["N"] == 3
        assert tracker.get_score(Color.BLACK) == 0

    def test_a_plain_move_with_no_capture_changes_no_score(self):
        board = TextBoard(["wR . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        tracker = ScoreTracker()

        tracker.update(_snap(state))
        engine.attempt_move(state, Position(0, 0), Position(0, 2))
        tracker.update(_snap(state))
        engine.tick(state, 2000)
        tracker.update(_snap(state))

        assert tracker.get_score(Color.WHITE) == 0
        assert tracker.get_score(Color.BLACK) == 0

    def test_pawn_promotion_is_not_scored_as_a_capture(self):
        """Same colour, same cell, kind changes (Pawn -> Queen) -- must
        not be mistaken for a capture, which always changes colour."""
        board = TextBoard([". . .", "wP . .", ". . ."])
        engine = GameEngine(board, cell_size=100, move_duration=100)
        state = GameState(board=board)
        tracker = ScoreTracker()

        tracker.update(_snap(state))
        engine.attempt_move(state, Position(1, 0), Position(0, 0))  # single-step advance
        tracker.update(_snap(state))
        engine.tick(state, 100)  # arrives at row 0 -> promotes to wQ
        assert state.board.get_piece_at(Position(0, 0)) == "wQ"

        tracker.update(_snap(state))
        assert tracker.get_score(Color.WHITE) == 0
        assert tracker.get_score(Color.BLACK) == 0

    def test_repeated_updates_on_an_unchanged_state_do_not_rescore(self):
        board = TextBoard(["wR . bN"])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        tracker = ScoreTracker()

        tracker.update(_snap(state))
        engine.attempt_move(state, Position(0, 0), Position(0, 2))
        engine.tick(state, 2000)
        tracker.update(_snap(state))
        assert tracker.get_score(Color.WHITE) == 3

        tracker.update(_snap(state))
        tracker.update(_snap(state))
        assert tracker.get_score(Color.WHITE) == 3


class TestMultipleCapturesInOneTick:
    def test_two_independent_captures_resolved_in_the_same_tick_are_both_counted(self):
        board = TextBoard(["wR . bN", ". . .", "bP . wR"])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        tracker = ScoreTracker()

        tracker.update(_snap(state))
        engine.attempt_move(state, Position(0, 0), Position(0, 2))  # wR captures bN
        engine.attempt_move(state, Position(2, 2), Position(2, 0))  # wR captures bP
        tracker.update(_snap(state))
        engine.tick(state, 2000)  # both arrive in the same tick
        tracker.update(_snap(state))

        assert tracker.get_score(Color.WHITE) == PIECE_POINTS["N"] + PIECE_POINTS["P"] == 4
        assert tracker.get_score(Color.BLACK) == 0

    def test_captures_by_both_colours_in_the_same_tick_score_independently(self):
        # wR's capture is horizontal (row 0); bR's is vertical (column 1)
        # -- different axes, so the opposite-colour common-route lock
        # (see test_realtime_conflicts.py's module docstring) doesn't
        # reject either move.
        board = TextBoard(["wR . bN", ". bR .", ". . .", ". wP ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        tracker = ScoreTracker()

        tracker.update(_snap(state))
        engine.attempt_move(state, Position(0, 0), Position(0, 2))  # wR captures bN
        engine.attempt_move(state, Position(1, 1), Position(3, 1))  # bR captures wP
        tracker.update(_snap(state))
        engine.tick(state, 2000)
        tracker.update(_snap(state))

        assert tracker.get_score(Color.WHITE) == PIECE_POINTS["N"] == 3
        assert tracker.get_score(Color.BLACK) == PIECE_POINTS["P"] == 1


class TestAirborneCaptureScoring:
    """Mirrors tests/unit/test_jump.py::TestAirborneCapture's own board
    and click sequence exactly, so this is proven against the same
    scenario that file already proves fires an AirborneCaptureEvent."""

    def _engine(self):
        board = TextBoard([". . .", "wK bR .", ". . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000, jump_duration=1000)
        state = GameState(board=board)
        return engine, state

    def test_the_defenders_colour_is_credited_for_the_attackers_value(self):
        engine, state = self._engine()
        tracker = ScoreTracker()

        tracker.update(_snap(state))
        engine.handle_jump(state, 50, 150)     # wK airborne at (1, 0)
        engine.handle_click(state, 150, 150)   # select bR
        engine.handle_click(state, 50, 150)    # queue bR -> (1, 0), attacking wK
        tracker.update(_snap(state))
        assert tracker.get_score(Color.WHITE) == 0  # not resolved yet

        engine.tick(state, 1000)  # bR is deleted outright; wK never moves
        tracker.update(_snap(state))

        assert tracker.get_score(Color.WHITE) == PIECE_POINTS["R"] == 5
        assert tracker.get_score(Color.BLACK) == 0

    def test_no_double_count_after_the_airborne_capture_resolves(self):
        engine, state = self._engine()
        tracker = ScoreTracker()

        tracker.update(_snap(state))
        engine.handle_jump(state, 50, 150)
        engine.handle_click(state, 150, 150)
        engine.handle_click(state, 50, 150)
        tracker.update(_snap(state))
        engine.tick(state, 1000)
        tracker.update(_snap(state))
        assert tracker.get_score(Color.WHITE) == 5

        engine.tick(state, 1000)  # wK grounds normally -- no further capture
        tracker.update(_snap(state))
        tracker.update(_snap(state))
        assert tracker.get_score(Color.WHITE) == 5


class TestAirborneCaptureFalsePositiveGuards:
    """The two ways a PendingMove can leave state.pending WITHOUT being an
    airborne capture, each engineered to coincide with an unrelated
    airborne enemy sitting at the move's own (now-moot) destination --
    exactly the scenario score_tracker.py's module docstring calls out
    as the reason _score_airborne_captures needs more than just "an
    enemy was airborne at to_pos"."""

    def test_a_piece_captured_at_its_own_origin_is_not_double_counted(self):
        # bN queues a long move; wR queues a shorter move that captures
        # bN at bN's own origin before bN's move would resolve. wK jumps
        # to bN's stale destination -- unrelated to the wR/bN fight.
        board = TextBoard(
            [
                "bN . . . wK",
                ". . . . .",
                "wR . . . .",
            ]
        )
        engine = GameEngine(board, cell_size=100, move_duration=1000, jump_duration=5000)
        state = GameState(board=board)
        tracker = ScoreTracker()

        tracker.update(_snap(state))
        engine.attempt_move(state, Position(0, 0), Position(0, 4))  # bN -> (0,4), 4000ms
        engine.attempt_move(state, Position(2, 0), Position(0, 0))  # wR -> (0,0), 2000ms
        engine.handle_jump(state, 420, 20)  # wK jumps in place at (0, 4)
        tracker.update(_snap(state))

        engine.tick(state, 2000)  # wR arrives, captures bN at its origin
        tracker.update(_snap(state))
        assert tracker.get_score(Color.WHITE) == PIECE_POINTS["N"] == 3

        engine.tick(state, 2000)  # bN's own stale move now resolves (dropped)
        tracker.update(_snap(state))

        assert tracker.get_score(Color.WHITE) == 3  # unchanged -- not double-counted
        assert tracker.get_score(Color.BLACK) == 0

    def test_a_friendly_block_stop_short_is_not_scored(self):
        board = TextBoard(["wR . . . bK"])
        engine = GameEngine(board, cell_size=100, move_duration=1000, jump_duration=5000)
        state = GameState(board=board)
        tracker = ScoreTracker()

        tracker.update(_snap(state))
        engine.attempt_move(state, Position(0, 0), Position(0, 4))  # wR -> (0,4), 4000ms
        state.board.set_piece_at(Position(0, 2), "wN")  # a friendly appears mid-route
        engine.handle_jump(state, 420, 20)  # bK jumps in place at (0, 4) -- unrelated
        tracker.update(_snap(state))

        engine.tick(state, 4000)  # wR stops short at (0,1) -- not a capture
        tracker.update(_snap(state))

        assert state.board.get_piece_at(Position(0, 1)) == "wR"
        assert tracker.get_score(Color.WHITE) == 0
        assert tracker.get_score(Color.BLACK) == 0


class TestScoreNeverDecreases:
    def test_score_only_ever_increases_across_several_captures(self):
        board = TextBoard(["wR . bN", ". . .", "bP . wR"])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        tracker = ScoreTracker()

        tracker.update(_snap(state))
        assert tracker.get_score(Color.WHITE) == 0

        engine.attempt_move(state, Position(0, 0), Position(0, 2))  # wR captures bN
        tracker.update(_snap(state))
        engine.tick(state, 2000)
        tracker.update(_snap(state))
        after_first = tracker.get_score(Color.WHITE)
        assert after_first == 3

        engine.attempt_move(state, Position(2, 2), Position(2, 0))  # wR captures bP
        tracker.update(_snap(state))
        engine.tick(state, 2000)
        tracker.update(_snap(state))
        after_second = tracker.get_score(Color.WHITE)

        assert after_second == after_first + PIECE_POINTS["P"] == 4
        assert after_second >= after_first  # never decreases
