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
                          *enemy* intervening arrival, or the origin piece
                          was captured first) and must be dropped silently.
  * Friendly mid-route  – a straight-line premove blocked partway by a
    block                *friendly* arrival doesn't drop entirely like the
                          enemy case above — the mover stops on the last
                          clear square before the blocker instead.
  * Movement conflicts – due moves are applied in chronological
                          (``arrival_time``) order within a tick, not queue
                          order, so which move "gets there first" is
                          determined by game time, not click order.

All scenarios avoid the opposite-colour common-route lock (see
test_transit_lock.py::TestOppositeColorRouteLock) by using moves on
different axes (one horizontal, one vertical) so both sides can be queued.

GameEngine owns no state of its own (Iteration 15) — every test builds
its own ``GameState`` and passes it explicitly to every engine call.
"""

from __future__ import annotations

from typing import List

from core.models import Position
from engine.board import TextBoard
from engine.game import GameEngine
from engine.game_state import GameState
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
    def _engine(self) -> tuple[GameEngine, GameState]:
        board = TextBoard(["wR . .", ". . .", ". . bR"])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        return engine, GameState(board=board)

    def test_later_arrival_captures_earlier_arrival_on_same_square(self):
        engine, state = self._engine()
        engine.handle_click(state, 0, 0)      # select wR
        engine.handle_click(state, 200, 0)    # queue wR -> (0,2)
        engine.handle_click(state, 200, 200)  # select bR
        engine.handle_click(state, 200, 0)    # queue bR -> (0,2)
        engine.tick(state, 2000)
        assert state.board.get_piece_at(Position(0, 2)) == "bR"

    def test_captured_piece_is_gone_and_origin_squares_are_empty(self):
        engine, state = self._engine()
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 200, 0)
        engine.handle_click(state, 200, 200)
        engine.handle_click(state, 200, 0)
        engine.tick(state, 2000)
        assert state.board.get_piece_at(Position(0, 0)) == "."
        assert state.board.get_piece_at(Position(2, 2)) == "."

    def test_both_moves_fire_a_move_completed_event(self):
        """Both moves were individually legal at the instant each was
        applied, so both raise MoveCompletedEvent — the second event just
        happens to overwrite the first's destination."""
        engine, state = self._engine()
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 200, 0)
        engine.handle_click(state, 200, 200)
        engine.handle_click(state, 200, 0)
        engine.tick(state, 2000)
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
    def _engine(self) -> tuple[GameEngine, GameState]:
        board = TextBoard(["wR . .", ". . .", ". . wR"])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        return engine, GameState(board=board)

    def test_second_friendly_arrival_on_occupied_square_is_rejected(self):
        engine, state = self._engine()
        engine.handle_click(state, 0, 0)      # select first wR
        engine.handle_click(state, 200, 0)    # queue -> (0,2)
        engine.handle_click(state, 200, 200)  # select second wR
        engine.handle_click(state, 200, 0)    # queue -> (0,2), same colour, same square
        engine.tick(state, 2000)
        assert state.board.get_piece_at(Position(0, 2)) == "wR"
        assert state.board.get_piece_at(Position(2, 2)) == "wR"

    def test_only_the_winning_move_fires_a_completed_event(self):
        engine, state = self._engine()
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 200, 0)
        engine.handle_click(state, 200, 200)
        engine.handle_click(state, 200, 0)
        engine.tick(state, 2000)
        assert len(obs.completed) == 1
        assert obs.completed[0].piece == "wR"
        assert obs.completed[0].from_pos == Position(0, 0)

    def test_blocked_piece_is_no_longer_in_transit_and_can_be_reselected(self):
        engine, state = self._engine()
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 200, 0)
        engine.handle_click(state, 200, 200)
        engine.handle_click(state, 200, 0)
        engine.tick(state, 2000)
        assert engine.is_in_transit(state, Position(2, 2)) is False
        engine.handle_click(state, 200, 200)
        assert engine.selection == Position(2, 2)


# ===========================================================================
# Invalid premoves
# ===========================================================================

class TestInvalidPremoves:
    def test_sliding_move_blocked_by_piece_that_moved_into_its_path(self):
        """wR (0,0) -> (0,3) is queued while the path is clear (3 cells,
        arrival = 3000). bK (1,1) -> (0,1) is queued too (1 cell, arrival
        = 1000) and lands squarely in the rook's path before the rook's
        own arrival. The rook's premove must be dropped."""
        board = TextBoard(["wR . . .", ". bK . .", ". . . .", ". . . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        engine.handle_click(state, 0, 0)      # select wR
        engine.handle_click(state, 300, 0)    # queue wR -> (0,3), path clear right now
        engine.handle_click(state, 100, 100)  # select bK
        engine.handle_click(state, 100, 0)    # queue bK -> (0,1)
        engine.tick(state, 3000)
        assert state.board.get_piece_at(Position(0, 0)) == "wR"
        assert state.board.get_piece_at(Position(0, 1)) == "bK"
        assert state.board.get_piece_at(Position(0, 3)) == "."

    def test_blocked_premove_fires_no_event_but_the_blocker_does(self):
        board = TextBoard(["wR . . .", ". bK . .", ". . . .", ". . . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 300, 0)
        engine.handle_click(state, 100, 100)
        engine.handle_click(state, 100, 0)
        engine.tick(state, 3000)
        assert [c.piece for c in obs.completed] == ["bK"]

    def test_origin_piece_captured_before_its_own_move_can_execute(self):
        """wK (0,0) queues a slow-arriving move; a bR captures wK's origin
        square in 1 cell, well before wK's own arrival. wK's queued move
        must not fire (nothing left to move)."""
        board = TextBoard(["wK . .", "bR . .", ". . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        engine.handle_click(state, 0, 0)      # select wK at (0,0)
        engine.handle_click(state, 200, 0)    # queue wK -> (0,2), 2 cells, arrival=2000
        engine.handle_click(state, 0, 100)    # select bR at (1,0)
        engine.handle_click(state, 0, 0)      # queue bR -> (0,0), 1 cell, arrival=1000
        engine.tick(state, 2000)
        # bR captured wK at (0,0) at t=1000; wK's own move never fires.
        assert state.board.get_piece_at(Position(0, 0)) == "bR"
        assert state.board.get_piece_at(Position(0, 2)) == "."


# ===========================================================================
# Friendly mid-route block: a same-colour piece appearing partway along a
# straight-line premove's path stops the mover short (on the last clear
# square before the blocker) instead of dropping the whole move. An enemy
# blocking the same way is unaffected — see TestInvalidPremoves above,
# whose enemy-blocker scenario still drops the whole move exactly as before.
# ===========================================================================

class TestFriendlyMidRouteBlock:
    def test_rook_stops_one_square_before_a_friendly_blocker(self):
        """wR (0,0) -> (0,3) is queued while the path is clear (arrival
        = 3000). A second wR (1,2) -> (0,2) is queued too (arrival =
        1000) and lands squarely in the first rook's path before its own
        arrival. The first rook must stop at (0,1) — the square just
        before the blocker — not be dropped entirely."""
        board = TextBoard(["wR . . .", ". . wR .", ". . . .", ". . . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        engine.handle_click(state, 0, 0)      # select first wR
        engine.handle_click(state, 300, 0)    # queue wR -> (0,3), path clear right now
        engine.handle_click(state, 250, 150)  # select second wR at (1,2)
        engine.handle_click(state, 250, 0)    # queue wR -> (0,2), arrives first (1 cell)
        engine.tick(state, 3000)
        assert state.board.get_piece_at(Position(0, 1)) == "wR"  # stopped short
        assert state.board.get_piece_at(Position(0, 2)) == "wR"  # the blocker
        assert state.board.get_piece_at(Position(0, 0)) == "."   # origin vacated
        assert state.board.get_piece_at(Position(0, 3)) == "."   # never reached

    def test_bishop_stops_before_a_friendly_blocker_on_the_diagonal(self):
        """wN (3,2) -> (1,1) is a legal Knight jump (2-and-1 shape,
        Chebyshev distance 2 -> arrival = 2000) that lands squarely on
        wB's diagonal, one step from its origin — arriving well before
        wB's own longer move (arrival = 3000). Since the blocker lands
        on (1,1) — the very first square of wB's diagonal — there is no
        clear square to stop on short of it, so wB never leaves (0,0)."""
        board = TextBoard(["wB . . .", ". . . .", ". . . .", ". . wN ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        engine.handle_click(state, 0, 0)      # select wB
        engine.handle_click(state, 300, 300)  # queue wB -> (3,3), path clear right now
        engine.handle_click(state, 250, 350)  # select wN at (3,2)
        engine.handle_click(state, 150, 150)  # queue wN -> (1,1), arrival = 2000
        engine.tick(state, 3000)
        assert state.board.get_piece_at(Position(0, 0)) == "wB"  # never left origin
        assert state.board.get_piece_at(Position(1, 1)) == "wN"  # the blocker
        assert state.board.get_piece_at(Position(3, 3)) == "."   # never reached

    def test_stopped_piece_fires_move_completed_event_with_the_short_destination(self):
        board = TextBoard(["wR . . .", ". . wR .", ". . . .", ". . . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 300, 0)
        engine.handle_click(state, 250, 150)
        engine.handle_click(state, 250, 0)
        engine.tick(state, 3000)
        completed = [c for c in obs.completed if c.piece == "wR" and c.from_pos == Position(0, 0)]
        assert len(completed) == 1
        assert completed[0].to_pos == Position(0, 1)

    def test_blocker_immediately_adjacent_to_origin_means_no_movement_at_all(self):
        """The blocker occupies the very first square of the route — there
        is no clear square to stop on, so the piece simply never leaves,
        and no MoveCompletedEvent fires for it."""
        board = TextBoard(["wR . . .", ". wR . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.handle_click(state, 0, 0)      # select wR at (0,0)
        engine.handle_click(state, 300, 0)    # queue wR -> (0,3)
        engine.handle_click(state, 150, 150)  # select second wR at (1,1)
        engine.handle_click(state, 150, 0)    # queue wR -> (0,1), the very first step
        engine.tick(state, 3000)
        assert state.board.get_piece_at(Position(0, 0)) == "wR"  # never moved
        assert not any(c.from_pos == Position(0, 0) for c in obs.completed)

    def test_enemy_blocker_mid_route_still_drops_the_whole_move(self):
        """Same idea as the friendly-blocker test above, but the blocker
        is an enemy — the existing (pre-rule) behaviour must be
        unchanged: the whole premove is dropped, mover stays at origin.
        bN (2,1) -> (0,2) is a legal Knight jump (Chebyshev distance 2 ->
        arrival = 2000), landing on wR's path before wR's own (arrival =
        3000) move resolves."""
        board = TextBoard(["wR . . .", ". . . .", ". bN . .", ". . . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        engine.handle_click(state, 0, 0)      # select wR
        engine.handle_click(state, 300, 0)    # queue wR -> (0,3), path clear right now
        engine.handle_click(state, 150, 250)  # select bN at (2,1)
        engine.handle_click(state, 250, 0)    # queue bN -> (0,2), arrival = 2000
        engine.tick(state, 3000)
        assert state.board.get_piece_at(Position(0, 0)) == "wR"  # dropped, not stopped short
        assert state.board.get_piece_at(Position(0, 1)) == "."

    def test_knight_move_is_never_affected_by_this_rule(self):
        """A Knight's move has no 'straight-line route' at all — the rule
        must not apply to it regardless of what's on the board."""
        board = TextBoard(["wN . .", ". . .", ". . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        engine.handle_click(state, 0, 0)      # select wN
        engine.handle_click(state, 150, 250)  # queue wN -> (2,1), a normal L-shape
        engine.tick(state, 2000)
        assert state.board.get_piece_at(Position(2, 1)) == "wN"

    def test_adjacent_one_cell_move_has_no_intermediate_square_to_block(self):
        board = TextBoard(["wR wR ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        engine.handle_click(state, 100, 0)    # select the second wR at (0,1)
        engine.handle_click(state, 200, 0)    # queue wR -> (0,2), 1 cell, no route to block
        engine.tick(state, 1000)
        assert state.board.get_piece_at(Position(0, 2)) == "wR"

    def test_pawn_two_step_blocked_by_friendly_on_its_only_intermediate_square(self):
        """The Pawn's two-step advance has exactly one intermediate
        square; a friendly piece there leaves nowhere to stop short of
        the origin, so the pawn simply never advances.

        4-row board: White's start row is num_rows - 2 = 2, so wP starts
        there; wN sits on the (only) intermediate square, (1,0)."""
        board = TextBoard([". . .", "wN . .", "wP . .", ". . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        engine.handle_click(state, 0, 200)    # select wP at (2,0), on its start row
        engine.handle_click(state, 0, 0)      # queue two-step to (0,0), path clear right now
        engine.tick(state, 2000)
        assert state.board.get_piece_at(Position(2, 0)) == "wP"  # never advanced
        assert state.board.get_piece_at(Position(1, 0)) == "wN"  # blocker unmoved
        assert state.board.get_piece_at(Position(0, 0)) == "."

    def test_second_rook_stops_behind_wherever_the_first_one_lands(self):
        """Rook A (0,0) queues a short 2-cell move to (0,2). Rook B (0,4)
        queues a 3-cell move to (0,1) — legal when queued, since (0,2) is
        still empty (Rook A hasn't moved yet).

        Rook A (2 cells, arrival 2000) arrives before Rook B (3 cells,
        arrival 3000) and lands on (0,2) — squarely in Rook B's path.
        Rook B must then stop at (0,3), the square just before Rook A's
        NEW position (which didn't exist yet when Rook B was queued)."""
        board = TextBoard(["wR . . . wR"])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        engine.handle_click(state, 50, 50)    # select Rook A at (0,0)
        engine.handle_click(state, 250, 50)   # queue A -> (0,2), arrival = 2000
        engine.handle_click(state, 450, 50)   # select Rook B at (0,4)
        engine.handle_click(state, 150, 50)   # queue B -> (0,1), arrival = 3000
        engine.tick(state, 3000)
        assert state.board.get_piece_at(Position(0, 2)) == "wR"  # Rook A's new spot
        assert state.board.get_piece_at(Position(0, 3)) == "wR"  # Rook B stopped short
        assert state.board.get_piece_at(Position(0, 0)) == "."   # Rook A's old spot
        assert state.board.get_piece_at(Position(0, 4)) == "."   # Rook B's old spot


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
        board = TextBoard(["wR . . .", ". . . .", ". . . bK", ". . . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        obs = _RecordingObserver()
        engine.add_observer(obs)

        engine.handle_click(state, 0, 0)      # select wR
        engine.handle_click(state, 300, 0)    # queue wR -> (0,3), arrival=3000 (queued 1st)
        engine.handle_click(state, 300, 200)  # select bK
        engine.handle_click(state, 300, 100)  # queue bK -> (1,3), arrival=1000 (queued 2nd)

        assert state.pending[0].piece == "wR"
        assert state.pending[1].piece == "bK"

        engine.tick(state, 3000)

        assert [c.piece for c in obs.completed] == ["bK", "wR"]

    def test_both_moves_land_correctly_despite_reversed_queue_order(self):
        board = TextBoard(["wR . . .", ". . . .", ". . . bK", ". . . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 300, 0)
        engine.handle_click(state, 300, 200)
        engine.handle_click(state, 300, 100)
        engine.tick(state, 3000)
        assert state.board.get_piece_at(Position(0, 3)) == "wR"
        assert state.board.get_piece_at(Position(1, 3)) == "bK"


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
