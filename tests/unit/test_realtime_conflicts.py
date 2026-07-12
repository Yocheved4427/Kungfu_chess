"""
Unit tests for advanced real-time interaction cases (Kung Fu Chess).

Because moves are asynchronous (queued on ``click``, applied on ``tick`` at
``arrival_time``), the board can change between the moment a move is queued
and the moment it resolves. This file covers the interaction cases that
only arise from that gap:

  * Enemy collisions   – two opposite-colour moves converge on the same
                          square in the same tick; the later-arriving one
                          captures whatever is there (including a piece
                          that landed a moment earlier in the same tick).
  * Friendly landing   – a move whose destination has since been filled by
                          a *friendly* piece is rejected at execution time,
                          not just at queue time.
  * Invalid premoves   – a move that was legal when queued (clear path,
                          piece present at origin) can become illegal by
                          the time it resolves (path blocked by an
                          intervening arrival, or the origin piece was
                          captured first) and must be dropped silently.
  * Movement conflicts – due moves are applied in chronological
                          (``arrival_time``) order within a tick, not queue
                          order, so which move "gets there first" is
                          determined by game time, not click order.

All scenarios avoid the opposite-colour common-route lock (see
test_transit_lock.py::TestOppositeColorRouteLock) by using moves on
different axes (one horizontal, one vertical) so both sides can be queued.
"""

from __future__ import annotations

from typing import List

from core.models import Position
from engine.board import TextBoard
from engine.game import GameEngine
from ui.events import GameEvent, MoveCompletedEvent, Observer


class _RecordingObserver(Observer):
    def __init__(self) -> None:
        self.events: List[GameEvent] = []

    def on_event(self, event: GameEvent) -> None:
        self.events.append(event)

    @property
    def completed(self) -> List[MoveCompletedEvent]:
        return [e for e in self.events if isinstance(e, MoveCompletedEvent)]


# ===========================================================================
# Enemy collisions
# ===========================================================================
#
# Board (3x3, cell_size=100, move_duration=1000 ms/cell):
#   row 0: "wR . ."
#   row 1: ".  . ."
#   row 2: ".  . bR"
#
# wR slides right (0,0)->(0,2): horizontal, 2 cells, arrival = 2000.
# bR slides up    (2,2)->(0,2): vertical,   2 cells, arrival = 2000.
# Same arrival_time, different axis (no route-lock). wR is queued first so
# it is applied first on the tie; bR is then re-validated against the
# post-wR board and finds an *enemy* on (0,2) — a legal capture.
# ===========================================================================

class TestEnemyCollision:
    def _engine(self) -> GameEngine:
        board = TextBoard(["wR . .", ". . .", ". . bR"])
        return GameEngine(board, cell_size=100, move_duration=1000)

    def test_later_arrival_captures_earlier_arrival_on_same_square(self):
        engine = self._engine()
        engine.handle_click(0, 0)      # select wR
        engine.handle_click(200, 0)    # queue wR -> (0,2)
        engine.handle_click(200, 200)  # select bR
        engine.handle_click(200, 0)    # queue bR -> (0,2)
        engine.tick(2000)
        assert engine.board.get_piece_at(Position(0, 2)) == "bR"

    def test_captured_piece_is_gone_and_origin_squares_are_empty(self):
        engine = self._engine()
        engine.handle_click(0, 0)
        engine.handle_click(200, 0)
        engine.handle_click(200, 200)
        engine.handle_click(200, 0)
        engine.tick(2000)
        assert engine.board.get_piece_at(Position(0, 0)) == "."
        assert engine.board.get_piece_at(Position(2, 2)) == "."

    def test_both_moves_fire_a_move_completed_event(self):
        """Both moves were individually legal at the instant each was
        applied, so both raise MoveCompletedEvent — the second event just
        happens to overwrite the first's destination."""
        engine = self._engine()
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.handle_click(0, 0)
        engine.handle_click(200, 0)
        engine.handle_click(200, 200)
        engine.handle_click(200, 0)
        engine.tick(2000)
        assert [c.piece for c in obs.completed] == ["wR", "bR"]


# ===========================================================================
# Friendly-piece landing
# ===========================================================================
#
# Same geometry as above but both rooks are white. The second (later in
# queue, tied arrival_time) arrival finds a *friendly* piece on the
# destination and must be rejected — not captured, not swapped.
# ===========================================================================

class TestFriendlyPieceLanding:
    def _engine(self) -> GameEngine:
        board = TextBoard(["wR . .", ". . .", ". . wR"])
        return GameEngine(board, cell_size=100, move_duration=1000)

    def test_second_friendly_arrival_on_occupied_square_is_rejected(self):
        engine = self._engine()
        engine.handle_click(0, 0)      # select first wR
        engine.handle_click(200, 0)    # queue -> (0,2)
        engine.handle_click(200, 200)  # select second wR
        engine.handle_click(200, 0)    # queue -> (0,2), same colour, same square
        engine.tick(2000)
        assert engine.board.get_piece_at(Position(0, 2)) == "wR"
        assert engine.board.get_piece_at(Position(2, 2)) == "wR"

    def test_only_the_winning_move_fires_a_completed_event(self):
        engine = self._engine()
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.handle_click(0, 0)
        engine.handle_click(200, 0)
        engine.handle_click(200, 200)
        engine.handle_click(200, 0)
        engine.tick(2000)
        assert len(obs.completed) == 1
        assert obs.completed[0].piece == "wR"
        assert obs.completed[0].from_pos == Position(0, 0)

    def test_blocked_piece_is_no_longer_in_transit_and_can_be_reselected(self):
        engine = self._engine()
        engine.handle_click(0, 0)
        engine.handle_click(200, 0)
        engine.handle_click(200, 200)
        engine.handle_click(200, 0)
        engine.tick(2000)
        assert engine.is_in_transit(Position(2, 2)) is False
        engine.handle_click(200, 200)
        assert engine.selection == Position(2, 2)


# ===========================================================================
# Invalid premoves
# ===========================================================================

class TestInvalidPremoves:
    """These tests are specifically about the queued attempt_move/tick()
    pipeline's re-validate-at-arrival behaviour — try_move (what
    handle_click uses now) applies instantly, so there's no premove
    window for a blocker to invalidate. Driven via attempt_move directly."""

    def test_sliding_move_blocked_by_piece_that_moved_into_its_path(self):
        """wR (0,0) -> (0,3) is queued while the path is clear (3 cells,
        arrival = 3000). bK (1,1) -> (0,1) is queued too (1 cell, arrival
        = 1000) and lands squarely in the rook's path before the rook's
        own arrival. The rook's premove must be dropped."""
        board = TextBoard(["wR . . .", ". bK . .", ". . . .", ". . . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        engine.attempt_move(Position(0, 0), Position(0, 3))  # path clear right now
        engine.attempt_move(Position(1, 1), Position(0, 1))
        engine.tick(3000)
        assert engine.board.get_piece_at(Position(0, 0)) == "wR"
        assert engine.board.get_piece_at(Position(0, 1)) == "bK"
        assert engine.board.get_piece_at(Position(0, 3)) == "."

    def test_blocked_premove_fires_no_event_but_the_blocker_does(self):
        board = TextBoard(["wR . . .", ". bK . .", ". . . .", ". . . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.attempt_move(Position(0, 0), Position(0, 3))
        engine.attempt_move(Position(1, 1), Position(0, 1))
        engine.tick(3000)
        assert [c.piece for c in obs.completed] == ["bK"]

    def test_origin_piece_captured_before_its_own_move_can_execute(self):
        """wK (0,0) queues a slow-arriving move; a bR captures wK's origin
        square in 1 cell, well before wK's own arrival. wK's queued move
        must not fire (nothing left to move)."""
        board = TextBoard(["wK . .", "bR . .", ". . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        engine.handle_click(0, 0)      # select wK at (0,0)
        engine.handle_click(200, 0)    # queue wK -> (0,2), 2 cells, arrival=2000
        engine.handle_click(0, 100)    # select bR at (1,0)
        engine.handle_click(0, 0)      # queue bR -> (0,0), 1 cell, arrival=1000
        engine.tick(2000)
        # bR captured wK at (0,0) at t=1000; wK's own move never fires.
        assert engine.board.get_piece_at(Position(0, 0)) == "bR"
        assert engine.board.get_piece_at(Position(0, 2)) == "."


# ===========================================================================
# Movement conflicts: due moves resolve in arrival-time order, not queue order
# ===========================================================================
#
# Board (4x4, cell_size=100, move_duration=1000 ms/cell):
#   row 0: "wR . . ."
#   row 1: ". . . ."
#   row 2: ". . . bK"
#   row 3: ". . . ."
#
# wR (0,0)->(0,3) is queued FIRST but takes 3 cells (arrival=3000).
# bK (2,3)->(1,3) is queued SECOND but takes only 1 cell (arrival=1000).
# Both are unrelated (no shared square) so both simply execute — this test
# only asserts the *order* of MoveCompletedEvents follows game time.
# ===========================================================================

class TestChronologicalDueOrder:
    def test_events_fire_in_arrival_time_order_not_queue_order(self):
        """Needs genuine queueing to observe arrival-time ordering, so
        it's driven via attempt_move directly rather than a click."""
        board = TextBoard(["wR . . .", ". . . .", ". . . bK", ". . . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        obs = _RecordingObserver()
        engine.add_observer(obs)

        engine.attempt_move(Position(0, 0), Position(0, 3))  # arrival=3000 (queued 1st)
        engine.attempt_move(Position(2, 3), Position(1, 3))  # arrival=1000 (queued 2nd)

        assert engine._pending[0].piece == "wR"
        assert engine._pending[1].piece == "bK"

        engine.tick(3000)

        assert [c.piece for c in obs.completed] == ["bK", "wR"]

    def test_both_moves_land_correctly_despite_reversed_queue_order(self):
        board = TextBoard(["wR . . .", ". . . .", ". . . bK", ". . . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        engine.handle_click(0, 0)
        engine.handle_click(300, 0)
        engine.handle_click(300, 200)
        engine.handle_click(300, 100)
        engine.tick(3000)
        assert engine.board.get_piece_at(Position(0, 3)) == "wR"
        assert engine.board.get_piece_at(Position(1, 3)) == "bK"


# ===========================================================================
# _lane() — direct unit coverage (staticmethod, independent of handle_click)
# ===========================================================================

class TestLaneHelper:
    def test_horizontal_move_returns_col_lane(self):
        assert GameEngine._lane(Position(0, 0), Position(0, 2)) == ("col", 0, 2)

    def test_horizontal_move_lane_is_order_independent(self):
        assert GameEngine._lane(Position(0, 2), Position(0, 0)) == ("col", 0, 2)

    def test_vertical_move_returns_row_lane(self):
        assert GameEngine._lane(Position(0, 1), Position(3, 1)) == ("row", 0, 3)

    def test_diagonal_move_returns_none(self):
        assert GameEngine._lane(Position(0, 0), Position(2, 2)) is None

    def test_knight_shaped_move_returns_none(self):
        assert GameEngine._lane(Position(0, 0), Position(2, 1)) is None

    def test_zero_distance_returns_none(self):
        assert GameEngine._lane(Position(1, 1), Position(1, 1)) is None
