"""
Unit tests for the transit-lock feature (Kungfu Chess).

A piece that is mid-movement (its PendingMove has not yet arrived) must:
  - be impossible to select.
  - be impossible to redirect, even via a friendly re-selection.
  - become freely movable again the instant it arrives (no cooldown).

Board used in most tests (3×3, cell_size=100):
    row 0: "wK . ."
    row 1: ".  . ."
    row 2: ".  . ."
  wK starts at (0,0).  move_duration=500 ms/cell.
"""

import pytest

from core.models import Position
from engine.board import TextBoard
from engine.game import GameEngine
from engine.rules import MoveValidator


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_ROWS_3x3 = ["wK . .", ". . .", ". . ."]


def _engine_3x3() -> GameEngine:
    return GameEngine(TextBoard(_ROWS_3x3), cell_size=100, move_duration=500)


# ===========================================================================
# is_in_transit helper
# ===========================================================================

class TestIsInTransit:
    def test_not_in_transit_before_any_move(self):
        engine = _engine_3x3()
        assert engine.is_in_transit(Position(0, 0)) is False

    def test_in_transit_immediately_after_queuing(self):
        engine = _engine_3x3()
        engine.handle_click(0, 0)    # select wK at (0,0)
        engine.handle_click(100, 0)  # move to (0,1) — 1 cell → arrives at 500 ms
        assert engine.is_in_transit(Position(0, 0)) is True

    def test_not_in_transit_while_clock_has_not_reached_arrival(self):
        engine = _engine_3x3()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)  # arrival_time = 500 ms
        engine.tick(499)             # still in transit
        assert engine.is_in_transit(Position(0, 0)) is True

    def test_not_in_transit_after_arrival(self):
        engine = _engine_3x3()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)  # arrival_time = 500 ms
        engine.tick(500)             # move executes, wK now at (0,1)
        assert engine.is_in_transit(Position(0, 1)) is False

    def test_arbitrary_empty_square_never_in_transit(self):
        engine = _engine_3x3()
        assert engine.is_in_transit(Position(1, 1)) is False


# ===========================================================================
# Cannot select an in-transit piece
# ===========================================================================

class TestCannotSelectInTransit:
    def test_click_in_transit_origin_does_not_select(self):
        engine = _engine_3x3()
        engine.handle_click(0, 0)    # select wK
        engine.handle_click(100, 0)  # queue move: wK → (0,1)
        # wK is physically still at (0,0) but in transit
        engine.handle_click(0, 0)    # attempt to select wK again
        assert engine.selection is None

    def test_click_in_transit_origin_does_not_select_mid_tick(self):
        engine = _engine_3x3()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)  # arrival = 500 ms
        engine.tick(250)             # half-way; piece still in transit
        engine.handle_click(0, 0)    # attempt select
        assert engine.selection is None


# ===========================================================================
# Cannot redirect an in-transit piece
# ===========================================================================

class TestCannotRedirectInTransit:
    def test_redirect_attempt_leaves_original_pending_move_intact(self):
        """Trying to select and redirect an in-transit piece must not alter
        the pending move queue."""
        engine = _engine_3x3()
        # Queue: wK (0,0) → (0,1), arrives at 500 ms
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)
        # Attempt to redirect: click origin (blocked) then new destination
        engine.handle_click(0, 0)    # blocked — no selection acquired
        engine.handle_click(0, 100)  # attempt redirect to (1,0) — should be ignored
        assert len(engine._pending) == 1
        assert engine._pending[0].to_pos == Position(0, 1)

    def test_second_pending_move_not_added_when_redirected(self):
        engine = _engine_3x3()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)  # queue: wK → (0,1), arrives at 500 ms
        engine.handle_click(0, 0)    # attempt re-select (blocked)
        engine.handle_click(200, 0)  # attempt redirect to (0,2)
        assert len(engine._pending) == 1


# ===========================================================================
# No cooldown after arrival
# ===========================================================================

class TestNoCooldownAfterArrival:
    def test_piece_selectable_immediately_after_arrival(self):
        engine = _engine_3x3()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)  # queue: wK → (0,1), arrives at 500 ms
        engine.tick(500)             # move executes
        engine.handle_click(100, 0)  # select wK at its new position (0,1)
        assert engine.selection == Position(0, 1)

    def test_move_queueable_immediately_after_arrival(self):
        engine = _engine_3x3()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)  # wK → (0,1), arrives at 500 ms
        engine.tick(500)
        # Immediately queue a new move — no extra wait required
        engine.handle_click(100, 0)  # select wK at (0,1)
        engine.handle_click(200, 0)  # move to (0,2)
        assert len(engine._pending) == 1
        assert engine._pending[0].from_pos == Position(0, 1)
        assert engine._pending[0].to_pos == Position(0, 2)

    def test_arrival_exactly_on_tick_is_not_in_transit(self):
        engine = _engine_3x3()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)  # arrives at 500 ms
        engine.tick(500)
        assert engine.is_in_transit(Position(0, 1)) is False


# ===========================================================================
# Friendly re-selection blocked when target is in transit
# ===========================================================================

class TestFriendlyReselectionBlocked:
    def test_cannot_switch_selection_to_in_transit_friendly(self):
        """Player has piece A selected; clicking an in-transit friendly B
        must NOT transfer selection to B."""
        board = TextBoard(["wK wR .", ". . .", ". . ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        # Queue wR (0,1) → (0,2)
        engine.handle_click(100, 0)  # select wR
        engine.handle_click(200, 0)  # queue move; wR in transit
        # Select wK, then try to switch to in-transit wR
        engine.handle_click(0, 0)    # select wK
        engine.handle_click(100, 0)  # click wR (in transit) — should be blocked
        assert engine.selection == Position(0, 0)

    def test_selection_unchanged_when_friendly_in_transit_clicked(self):
        """The selection variable holds the last valid selection; a blocked
        re-selection must leave it unchanged."""
        board = TextBoard(["wK wR .", ". . .", ". . ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        engine.handle_click(100, 0)  # select wR
        engine.handle_click(200, 0)  # wR in transit
        engine.handle_click(0, 0)    # select wK → selection = (0,0)
        before = engine.selection
        engine.handle_click(100, 0)  # attempt to switch to in-transit wR
        assert engine.selection == before


# ===========================================================================
# Redirect-lock scenarios (explicit four cases requested)
# ===========================================================================
#
# Board (3×3, cell_size=100, move_duration=500 ms/cell):
#   row 0: "wK . ."
#   row 1: ".  . ."
#   row 2: ".  . ."
#
# Pixel → cell: x // 100 = col, y // 100 = row.
# wK at (0,0).  One-cell king move arrives at t = 500 ms.
# ===========================================================================

class TestRedirectLockScenarios:
    """Four explicit scenarios for the in-transit redirect lock."""

    # ------------------------------------------------------------------
    # 1. Redirect while mid-movement → rejected; piece arrives at original dest
    # ------------------------------------------------------------------

    def test_redirect_mid_transit_piece_arrives_at_original_destination(self):
        """A redirect command issued while the piece is in transit must be
        rejected.  The piece must still arrive at its original destination
        when tick() reaches arrival_time."""
        engine = _engine_3x3()
        # Queue: wK (0,0) → (0,1), arrives at t=500.
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)

        # Mid-transit: try to redirect to (1,0).
        engine.handle_click(0, 0)    # attempt select — blocked (in transit)
        engine.handle_click(0, 100)  # attempt redirect to (1,0) — ignored

        # Advance clock to arrival.
        engine.tick(500)

        # Piece must be at the original destination, not the redirect target.
        assert engine.board.get_piece_at(Position(0, 1)) == "wK"
        assert engine.board.get_piece_at(Position(1, 0)) == "."
        assert engine.board.get_piece_at(Position(0, 0)) == "."

    def test_redirect_mid_transit_queue_has_exactly_one_pending_move(self):
        """A redirect attempt must not add a second entry to the pending queue."""
        engine = _engine_3x3()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)  # original move queued

        engine.handle_click(0, 0)    # redirect: select blocked
        engine.handle_click(0, 100)  # redirect: destination ignored

        assert len(engine._pending) == 1
        assert engine._pending[0].to_pos == Position(0, 1)

    # ------------------------------------------------------------------
    # 2. Piece arrives → immediately accepts a new move, no cooldown
    # ------------------------------------------------------------------

    def test_new_move_accepted_on_same_tick_as_arrival(self):
        """After tick() executes the arriving move the piece must be
        selectable and movable in the very next handle_click — same clock
        value, no extra wait."""
        engine = _engine_3x3()
        # wK (0,0) → (0,1), arrives at t=500.
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)
        engine.tick(500)  # move executes; clock = 500

        # Select and move the piece immediately (clock still at 500).
        engine.handle_click(100, 0)  # select wK at (0,1)
        engine.handle_click(200, 0)  # move to (0,2)

        assert len(engine._pending) == 1
        assert engine._pending[0].from_pos == Position(0, 1)
        assert engine._pending[0].to_pos == Position(0, 2)
        # arrival_time of the new move must be relative to current clock (500).
        assert engine._pending[0].arrival_time == 1000  # 500 + 1 cell * 500 ms

    def test_piece_not_in_transit_after_arrival_allows_selection(self):
        """is_in_transit must be False right after the arriving tick so the
        engine's selection guard does not block the piece."""
        engine = _engine_3x3()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)  # arrives at t=500
        engine.tick(500)

        assert engine.is_in_transit(Position(0, 1)) is False
        engine.handle_click(100, 0)
        assert engine.selection == Position(0, 1)

    # ------------------------------------------------------------------
    # 3. Edge case: redirect sent at the exact tick of arrival
    # ------------------------------------------------------------------

    def test_redirect_one_ms_before_arrival_is_blocked(self):
        """At t = arrival_time - 1 the piece is still in transit; a redirect
        attempt at that instant must be rejected."""
        engine = _engine_3x3()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)  # arrival_time = 500
        engine.tick(499)             # one ms before arrival

        # Still in transit — redirect must be blocked.
        engine.handle_click(0, 0)    # select blocked
        engine.handle_click(0, 100)  # destination ignored
        assert len(engine._pending) == 1
        assert engine._pending[0].to_pos == Position(0, 1)

    def test_move_command_accepted_after_tick_that_executes_arrival(self):
        """tick(arrival_time) executes the move.  The very next handle_click
        after that tick must be able to queue a new move."""
        engine = _engine_3x3()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)  # arrival_time = 500
        engine.tick(499)             # one ms before — piece still in transit
        engine.tick(1)               # arrival tick — move executes (clock = 500)

        engine.handle_click(100, 0)  # select wK at new pos (0,1)
        engine.handle_click(200, 0)  # move to (0,2)
        assert len(engine._pending) == 1
        assert engine._pending[0].from_pos == Position(0, 1)

    def test_redirect_and_then_arrival_piece_at_original_destination(self):
        """Redirect at t=arrival_time-1 is rejected; piece still arrives at
        the original destination when the final tick fires."""
        engine = _engine_3x3()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)  # wK → (0,1), arrival_time = 500
        engine.tick(499)             # blocked redirect window
        engine.handle_click(0, 0)    # attempt select
        engine.handle_click(0, 100)  # attempt redirect to (1,0)
        engine.tick(1)               # arrival fires

        assert engine.board.get_piece_at(Position(0, 1)) == "wK"
        assert engine.board.get_piece_at(Position(1, 0)) == "."

    # ------------------------------------------------------------------
    # 4. Edge case: multiple redirect attempts during one transit
    # ------------------------------------------------------------------

    def test_three_redirect_attempts_all_rejected(self):
        """Every redirect attempt during a single transit must be silently
        ignored regardless of how many are made."""
        engine = _engine_3x3()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)  # wK → (0,1), arrival_time = 500

        # Three separate redirect attempts at different clock points.
        engine.tick(100)
        engine.handle_click(0, 0); engine.handle_click(0, 100)   # attempt 1

        engine.tick(100)
        engine.handle_click(0, 0); engine.handle_click(200, 0)   # attempt 2

        engine.tick(100)
        engine.handle_click(0, 0); engine.handle_click(0, 200)   # attempt 3

        # Only the original move must still be pending.
        assert len(engine._pending) == 1
        assert engine._pending[0].to_pos == Position(0, 1)

    def test_multiple_redirects_piece_arrives_at_original_destination(self):
        """After many rejected redirects the piece must complete its original
        route correctly when arrival_time is reached."""
        engine = _engine_3x3()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)  # wK → (0,1), arrival_time = 500

        for _ in range(5):
            engine.handle_click(0, 0)    # select blocked
            engine.handle_click(0, 100)  # redirect ignored

        engine.tick(500)  # arrival

        assert engine.board.get_piece_at(Position(0, 1)) == "wK"
        assert engine.board.get_piece_at(Position(0, 0)) == "."
        assert engine.board.get_piece_at(Position(1, 0)) == "."

    def test_redirect_attempts_do_not_corrupt_pending_queue(self):
        """Pending queue must stay exactly length 1 throughout a transit
        no matter how many redirect attempts are made."""
        engine = _engine_3x3()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)

        for tick_step in (50, 50, 50, 50):
            engine.tick(tick_step)
            engine.handle_click(0, 0)    # select blocked
            engine.handle_click(0, 100)  # redirect ignored
            assert len(engine._pending) == 1


# ===========================================================================
# Route lock: opposite colours cannot move concurrently on a common route
# ===========================================================================
#
# Board (3x3, cell_size=100, move_duration=1000 ms/cell):
#   row 0: "wR . ."
#   row 1: ".  . ."
#   row 2: "bR . ."
#
# White slides row 0 across columns 0-2; Black slides row 2 across the same
# column span. Even though the two rows never touch, both moves occupy the
# same "route" (column span 0-2) at the same time, so the second mover
# (Black) must be rejected while it is queued.
# ===========================================================================

class TestOppositeColorRouteLock:
    def _engine(self) -> GameEngine:
        board = TextBoard(["wR . .", ". . .", "bR . ."])
        return GameEngine(board, cell_size=100, move_duration=1000)

    def test_second_mover_on_common_route_is_not_queued(self):
        engine = self._engine()
        engine.handle_click(50, 50)    # select wR (0,0)
        engine.handle_click(250, 50)   # queue wR -> (0,2), columns 0-2
        engine.handle_click(50, 250)   # select bR (2,0)
        engine.handle_click(250, 250)  # attempt bR -> (2,2), columns 0-2 - blocked
        assert len(engine._pending) == 1
        assert engine._pending[0].piece == "wR"

    def test_first_mover_still_arrives_second_mover_stays_put(self):
        engine = self._engine()
        engine.handle_click(50, 50)
        engine.handle_click(250, 50)
        engine.handle_click(50, 250)
        engine.handle_click(250, 250)
        engine.tick(2000)
        assert engine.board.get_piece_at(Position(0, 2)) == "wR"
        assert engine.board.get_piece_at(Position(2, 0)) == "bR"
        assert engine.board.get_piece_at(Position(2, 2)) == "."

    def test_same_color_common_route_is_not_blocked(self):
        """The lock only applies to opposite colours; two friendly pieces
        sharing a route may both be queued."""
        board = TextBoard(["wR . .", ". . .", "wR . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        engine.handle_click(50, 50)    # select first wR (0,0)
        engine.handle_click(250, 50)   # queue wR -> (0,2)
        engine.handle_click(50, 250)   # select second wR (2,0)
        engine.handle_click(250, 250)  # queue wR -> (2,2), same colour - allowed
        assert len(engine._pending) == 2

    def test_non_overlapping_columns_do_not_conflict(self):
        """Routes on disjoint column spans never conflict, even for
        opposite colours."""
        board = TextBoard(["wR . . . .", ". . . . .", ". . bR . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        engine.handle_click(50, 50)    # select wR (0,0)
        engine.handle_click(150, 50)   # queue wR -> (0,1), columns 0-1
        engine.handle_click(250, 250)  # select bR (2,2)
        engine.handle_click(450, 250)  # queue bR -> (2,4), columns 2-4 - no overlap
        assert len(engine._pending) == 2
