"""
Unit tests for engine/real_time_arbiter.py

Scope: RealTimeArbiter in complete isolation — no Board, no GameEngine,
no RuleEngine. Purely the virtual-clock scheduling contract.

IMPORTANT: every test in this file simulates elapsed time exclusively via
``arbiter.advance_time(ms)``. None of them call ``time.sleep`` (or any
other wall-clock mechanism) — that's the whole point of a deterministic,
virtual-clock arbiter: the same sequence of advance_time() calls always
produces the same result, instantly, with no real waiting.
"""

from __future__ import annotations

import pytest

from core.models import Position
from engine.real_time_arbiter import ActiveMove, RealTimeArbiter


# ===========================================================================
# Construction
# ===========================================================================

class TestConstruction:
    def test_starts_at_time_zero(self):
        assert RealTimeArbiter().current_time == 0

    def test_starts_with_no_active_moves(self):
        assert RealTimeArbiter().active_moves == []


# ===========================================================================
# start_move() / active_moves
# ===========================================================================

class TestStartMove:
    def test_registers_an_active_move(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        assert len(arbiter.active_moves) == 1

    def test_active_move_reports_full_remaining_time_immediately(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        assert arbiter.active_moves[0] == ActiveMove(
            piece="wR", from_pos=Position(0, 0), to_pos=Position(0, 2), remaining_ms=1000
        )

    def test_multiple_moves_tracked_independently(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        arbiter.start_move("bN", Position(2, 0), Position(0, 1), duration_ms=500)
        assert len(arbiter.active_moves) == 2

    def test_negative_duration_raises(self):
        with pytest.raises(ValueError):
            RealTimeArbiter().start_move("wR", Position(0, 0), Position(0, 1), duration_ms=-1)

    def test_zero_duration_move_is_active_but_immediately_due(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wK", Position(0, 0), Position(0, 1), duration_ms=0)
        assert arbiter.active_moves[0].remaining_ms == 0

    def test_starting_a_move_after_time_has_advanced_uses_current_time_as_origin(self):
        arbiter = RealTimeArbiter()
        arbiter.advance_time(500)
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        assert arbiter.active_moves[0].remaining_ms == 1000


# ===========================================================================
# advance_time() — the deterministic virtual clock
# ===========================================================================

class TestAdvanceTimeAccumulates:
    def test_current_time_increases_by_ms(self):
        arbiter = RealTimeArbiter()
        arbiter.advance_time(300)
        assert arbiter.current_time == 300

    def test_current_time_accumulates_across_calls(self):
        arbiter = RealTimeArbiter()
        arbiter.advance_time(300)
        arbiter.advance_time(200)
        assert arbiter.current_time == 500

    def test_advance_zero_does_not_change_time(self):
        arbiter = RealTimeArbiter()
        arbiter.advance_time(0)
        assert arbiter.current_time == 0

    def test_negative_ms_raises(self):
        with pytest.raises(ValueError):
            RealTimeArbiter().advance_time(-1)


class TestAdvanceTimeReducesRemaining:
    def test_partial_advance_reduces_remaining_ms(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        arbiter.advance_time(400)
        assert arbiter.active_moves[0].remaining_ms == 600

    def test_remaining_ms_keeps_reducing_across_multiple_advances(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        arbiter.advance_time(300)
        arbiter.advance_time(300)
        assert arbiter.active_moves[0].remaining_ms == 400

    def test_move_still_in_active_moves_one_ms_before_due(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        arbiter.advance_time(999)
        assert len(arbiter.active_moves) == 1
        assert arbiter.active_moves[0].remaining_ms == 1


class TestAdvanceTimeReturnsDueMoves:
    def test_exact_arrival_is_returned_as_due(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        due = arbiter.advance_time(1000)
        assert len(due) == 1
        assert due[0] == ActiveMove(
            piece="wR", from_pos=Position(0, 0), to_pos=Position(0, 2), remaining_ms=0
        )

    def test_overshooting_the_arrival_still_reports_it_due(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        due = arbiter.advance_time(5000)
        assert len(due) == 1

    def test_due_move_is_removed_from_active_moves(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        arbiter.advance_time(1000)
        assert arbiter.active_moves == []

    def test_not_yet_due_move_is_not_returned(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        due = arbiter.advance_time(500)
        assert due == []

    def test_zero_duration_move_becomes_due_on_advance_time_zero(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wK", Position(0, 0), Position(0, 1), duration_ms=0)
        due = arbiter.advance_time(0)
        assert len(due) == 1

    def test_multiple_moves_due_in_one_advance_are_all_returned(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=500)
        arbiter.start_move("bN", Position(2, 0), Position(0, 1), duration_ms=500)
        due = arbiter.advance_time(500)
        assert len(due) == 2

    def test_due_moves_are_chronologically_ordered(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("bN", Position(2, 0), Position(0, 1), duration_ms=800)
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=300)
        due = arbiter.advance_time(1000)
        assert [m.piece for m in due] == ["wR", "bN"]

    def test_only_due_moves_leave_active_moves_the_rest_remain(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=500)
        arbiter.start_move("bN", Position(2, 0), Position(0, 1), duration_ms=2000)
        due = arbiter.advance_time(500)
        assert [m.piece for m in due] == ["wR"]
        assert len(arbiter.active_moves) == 1
        assert arbiter.active_moves[0].piece == "bN"
        assert arbiter.active_moves[0].remaining_ms == 1500

    def test_due_move_across_several_small_advances(self):
        """Simulates elapsed time in small deterministic increments —
        still no sleep() anywhere, just repeated advance_time calls."""
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        for _ in range(9):
            assert arbiter.advance_time(100) == []
        due = arbiter.advance_time(100)
        assert len(due) == 1

    def test_advancing_after_all_moves_resolved_is_a_no_op(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=500)
        arbiter.advance_time(500)
        due = arbiter.advance_time(1000)
        assert due == []
        assert arbiter.active_moves == []


# ===========================================================================
# is_moving()
# ===========================================================================

class TestIsMoving:
    def test_true_immediately_after_start_move(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        assert arbiter.is_moving(Position(0, 0)) is True

    def test_false_for_an_unrelated_position(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        assert arbiter.is_moving(Position(5, 5)) is False

    def test_false_before_any_move_starts(self):
        assert RealTimeArbiter().is_moving(Position(0, 0)) is False

    def test_true_while_time_has_not_yet_reached_arrival(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        arbiter.advance_time(999)
        assert arbiter.is_moving(Position(0, 0)) is True

    def test_false_once_the_move_becomes_due(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        arbiter.advance_time(1000)
        assert arbiter.is_moving(Position(0, 0)) is False

    def test_destination_is_not_considered_moving(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        assert arbiter.is_moving(Position(0, 2)) is False


# ===========================================================================
# cancel_move()
# ===========================================================================

class TestCancelMove:
    def test_cancelling_an_active_move_removes_it(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        arbiter.cancel_move(Position(0, 0))
        assert arbiter.active_moves == []

    def test_cancel_returns_true_when_a_move_was_found(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        assert arbiter.cancel_move(Position(0, 0)) is True

    def test_cancel_returns_false_for_an_unknown_position(self):
        arbiter = RealTimeArbiter()
        assert arbiter.cancel_move(Position(9, 9)) is False

    def test_cancelled_move_is_never_returned_as_due(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        arbiter.cancel_move(Position(0, 0))
        due = arbiter.advance_time(5000)
        assert due == []

    def test_cancelling_one_move_does_not_affect_another(self):
        arbiter = RealTimeArbiter()
        arbiter.start_move("wR", Position(0, 0), Position(0, 2), duration_ms=1000)
        arbiter.start_move("bN", Position(2, 0), Position(0, 1), duration_ms=1000)
        arbiter.cancel_move(Position(0, 0))
        assert len(arbiter.active_moves) == 1
        assert arbiter.active_moves[0].piece == "bN"


# ===========================================================================
# ActiveMove — plain value object
# ===========================================================================

class TestActiveMove:
    def test_is_frozen_and_comparable_by_value(self):
        a = ActiveMove(piece="wK", from_pos=Position(0, 0), to_pos=Position(0, 1), remaining_ms=100)
        b = ActiveMove(piece="wK", from_pos=Position(0, 0), to_pos=Position(0, 1), remaining_ms=100)
        assert a == b
        with pytest.raises(AttributeError):
            a.remaining_ms = 50  # type: ignore[misc]
