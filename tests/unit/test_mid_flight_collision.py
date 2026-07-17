"""
Unit tests for ``paths_intersect_in_time`` (Kungfu Chess).

Standalone geometry/time capability — see realtime/mid_flight_collision.py's
module docstring for why it's separate from CollisionResolver. Nothing here
exercises GameEngine or the real move-resolution pipeline; this is pure
math against hand-built PendingMoves, verifying the function is correct in
isolation before any decision is made about wiring it into actual gameplay.

Each move is a straight line from ``from_pos`` to ``to_pos`` over
``[arrival_time - duration, arrival_time]``. Test boards are never
constructed — this function takes no board at all.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from core.models import PendingMove, Position
from realtime.mid_flight_collision import paths_intersect_in_time


def _pm(from_pos: Position, to_pos: Position, arrival_time: int, piece: str = "wR") -> PendingMove:
    return PendingMove(piece=piece, from_pos=from_pos, to_pos=to_pos, arrival_time=arrival_time)


class TestParallelPathsNeverMeet:
    def test_same_direction_constant_row_offset(self):
        """Two rooks sliding along adjacent rows, same speed, same
        direction, same time window -- never share a point."""
        a = _pm(Position(0, 0), Position(0, 3), arrival_time=300)
        b = _pm(Position(1, 0), Position(1, 3), arrival_time=300)
        assert paths_intersect_in_time(a, 300, b, 300) is None

    def test_opposite_direction_still_parallel(self):
        """Parallel doesn't require matching direction -- a constant
        non-zero gap on one axis rules out a collision regardless of the
        other axis."""
        a = _pm(Position(0, 0), Position(0, 3), arrival_time=300)
        b = _pm(Position(1, 3), Position(1, 0), arrival_time=300)
        assert paths_intersect_in_time(a, 300, b, 300) is None

    def test_row_and_col_would_only_match_at_different_times(self):
        """Neither a constant-gap parallel nor a real crossing: each axis
        has its own unique solution for t, and they disagree, so the two
        axes are never simultaneously equal."""
        a = _pm(Position(0, 0), Position(4, 4), arrival_time=4)
        b = _pm(Position(2, 0), Position(2, 8), arrival_time=4)
        assert paths_intersect_in_time(a, 4, b, 4) is None


class TestNoTimeOverlap:
    def test_one_move_lands_before_the_other_starts(self):
        """Even though the underlying lines cross in space, the two
        moves are never in flight at the same time at all."""
        a = _pm(Position(0, 0), Position(0, 4), arrival_time=100)
        b = _pm(Position(0, 4), Position(0, 0), arrival_time=1000)
        assert paths_intersect_in_time(a, 100, b, 100) is None

    def test_windows_touching_at_a_single_instant_with_no_shared_point(self):
        a = _pm(Position(0, 0), Position(0, 1), arrival_time=100)
        b = _pm(Position(5, 0), Position(5, 1), arrival_time=200)
        assert paths_intersect_in_time(a, 100, b, 100) is None


class TestCrossesGeometricallyButOutsideTheOverlapWindow:
    def test_algebraic_crossing_time_falls_after_the_overlap_ends(self):
        """Both pieces travel along row 0; their columns *would* meet at
        t=12.5, but A's own flight (and hence the overlap, [5, 10]) is
        over by t=10."""
        a = _pm(Position(0, 0), Position(0, 10), arrival_time=10)   # t in [0, 10], col(t) = t
        b = _pm(Position(0, 20), Position(0, 10), arrival_time=20)  # t in [5, 20], col(t) = 25 - t
        result = paths_intersect_in_time(a, 10, b, 15)
        assert result is None

    def test_confirms_the_pieces_are_genuinely_apart_at_the_overlap_boundary(self):
        """Same setup as above: at t=10 (end of the overlap), A is at
        col 10 and B is at col 15 -- sanity-checking the None result by
        hand rather than trusting the algebra alone."""
        a = _pm(Position(0, 0), Position(0, 10), arrival_time=10)
        b = _pm(Position(0, 20), Position(0, 10), arrival_time=20)
        assert paths_intersect_in_time(a, 10, b, 15) is None


class TestGenuineCrossingWithinTheWindow:
    def test_x_shaped_crossing_returns_the_crossing_time(self):
        """Two pieces sliding diagonally toward each other, crossing at
        the board's centre at t=2."""
        a = _pm(Position(0, 0), Position(4, 4), arrival_time=4)
        b = _pm(Position(0, 4), Position(4, 0), arrival_time=4)
        assert paths_intersect_in_time(a, 4, b, 4) == Fraction(2)

    def test_head_on_collision_on_the_same_line(self):
        """Two rooks sliding toward each other on the same row meet in
        the middle."""
        a = _pm(Position(0, 0), Position(0, 4), arrival_time=4)
        b = _pm(Position(0, 4), Position(0, 0), arrival_time=4)
        assert paths_intersect_in_time(a, 4, b, 4) == Fraction(2)

    def test_crossing_time_can_be_a_non_integer_fraction(self):
        """Two adjacent cells swapping places cross exactly halfway
        through -- the whole reason this returns an exact Fraction
        rather than a float."""
        a = _pm(Position(0, 0), Position(0, 1), arrival_time=1)
        b = _pm(Position(0, 1), Position(0, 0), arrival_time=1)
        result = paths_intersect_in_time(a, 1, b, 1)
        assert result == Fraction(1, 2)
        assert isinstance(result, Fraction)

    def test_crossing_at_the_exact_edge_of_the_overlap_window_counts(self):
        """Inclusive bounds: a crossing exactly at window_end (here, the
        single instant B starts flying, which is also when A finishes)
        still counts, mirroring the inclusive arrival_time <=
        current_time comparisons GameEngine.tick() uses.

        A finishes at col 10 at t=10; B starts at col 10 at t=10 too
        (window = [10, 10], a single instant) and then diverges (slope
        0.5 vs A's slope 1) -- so t=10 is the only candidate, and it's
        exactly at both window edges.
        """
        a = _pm(Position(0, 0), Position(0, 10), arrival_time=10)   # t in [0, 10], col(t) = t
        b = _pm(Position(0, 10), Position(0, 15), arrival_time=20)  # t in [10, 20]
        assert paths_intersect_in_time(a, 10, b, 10) == Fraction(10)

    def test_different_speeds_still_produce_a_correct_crossing_time(self):
        """A slower, longer move and a faster, shorter move crossing
        paths -- exercises unequal durations, not just symmetric ones."""
        a = _pm(Position(0, 0), Position(0, 8), arrival_time=8)   # duration 8, col(t) = t
        b = _pm(Position(0, 8), Position(0, 4), arrival_time=4)   # duration 4, col(t) = 8 - t
        # t = 8 - t -> t = 4
        assert paths_intersect_in_time(a, 8, b, 4) == Fraction(4)


class TestIdenticalOrOverlappingPaths:
    def test_identical_paths_collide_for_the_whole_overlap(self):
        """Same from/to/timing on both moves: every instant is a
        collision, not just one point -- the overlap's start is returned."""
        a = _pm(Position(0, 0), Position(0, 4), arrival_time=4)
        b = _pm(Position(0, 0), Position(0, 4), arrival_time=4)
        assert paths_intersect_in_time(a, 4, b, 4) == Fraction(0)

    def test_same_cells_retraced_later_is_not_actually_a_collision(self):
        """Counter-intuitive but correct: B travels the exact same
        cell-to-cell path as A, just starting 2ms later. That does NOT
        mean they collide -- at every shared instant B is exactly 2
        columns behind where A is (a constant gap, same as two cars
        holding the same speed and following distance), so this falls
        into the "parallel, constant non-zero offset" case, not
        "identical paths". Only truly identical timing (same
        arrival_time too, see test above) collides for a whole window."""
        a = _pm(Position(0, 0), Position(0, 4), arrival_time=4)    # t in [0, 4], col(t) = t
        b = _pm(Position(0, 0), Position(0, 4), arrival_time=6)    # t in [2, 6], col(t) = t - 2
        assert paths_intersect_in_time(a, 4, b, 4) is None

    def test_stationary_move_at_the_same_cell_as_another_stationary_move(self):
        """Degenerate but well-defined: a zero-length "move" (from_pos ==
        to_pos) has zero velocity; two coincident stationary points
        collide for their whole overlap."""
        a = _pm(Position(3, 3), Position(3, 3), arrival_time=100)
        b = _pm(Position(3, 3), Position(3, 3), arrival_time=200)
        assert paths_intersect_in_time(a, 100, b, 200) == Fraction(0)


class TestDurationValidation:
    def test_zero_duration_a_raises(self):
        a = _pm(Position(0, 0), Position(0, 1), arrival_time=0)
        b = _pm(Position(0, 0), Position(0, 1), arrival_time=1)
        with pytest.raises(ValueError, match="duration_a"):
            paths_intersect_in_time(a, 0, b, 1)

    def test_negative_duration_b_raises(self):
        a = _pm(Position(0, 0), Position(0, 1), arrival_time=1)
        b = _pm(Position(0, 0), Position(0, 1), arrival_time=1)
        with pytest.raises(ValueError, match="duration_b"):
            paths_intersect_in_time(a, 1, b, -5)
