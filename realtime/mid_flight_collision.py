from __future__ import annotations

from fractions import Fraction
from typing import Optional

from core.models import PendingMove

# ---------------------------------------------------------------------------
# Kung Fu Chess – Continuous-time mid-flight collision detection
# ---------------------------------------------------------------------------
# A separate module from realtime.collision_resolver, not a CollisionResolver
# method, because it's a different kind of question against different
# inputs: CollisionResolver decides what happens when a single DUE move
# meets the board's CURRENT occupants at a tick boundary (needs an
# AbstractBoard; only ever looks at one PendingMove at a time). This module
# asks whether two PendingMoves' straight-line paths cross the same point
# at the same instant while BOTH may still be mid-flight — no board
# involved at all, and always exactly two moves. See
# realtime.collision_resolver's own module docstring for what it covers
# instead.
#
# Standalone capability only, per explicit instruction: nothing here is
# called from GameEngine.tick() or anywhere else in the real
# move-resolution pipeline yet. Wiring this into actual gameplay (and
# deciding what "collision" should *do* to two crossing pieces) is a
# separate decision.
#
# Pure geometry/time math, no board mutation, no side effects, no event
# firing — same idiom as engine.geometry's shape helpers, just with a time
# dimension added. Every input (positions, arrival_time, duration) is an
# integer, so this uses fractions.Fraction throughout rather than float:
# an exact crossing time is very often non-integral (e.g. two pieces
# closing a 3-cell gap over 4 cells of combined travel cross at t = 3/4 of
# the way through), and float arithmetic would force an arbitrary epsilon
# tolerance into what is otherwise an exactly-solvable linear system —
# Fraction avoids that entirely.
# ---------------------------------------------------------------------------


def paths_intersect_in_time(
    move_a: PendingMove,
    duration_a: int,
    move_b: PendingMove,
    duration_b: int,
) -> Optional[Fraction]:
    """Return the game-clock time (ms) at which *move_a* and *move_b*'s
    straight-line paths occupy the same point, or ``None`` if they never
    do while both are actually in flight.

    Each move is treated as travelling at constant velocity in a straight
    line from ``from_pos`` to ``to_pos`` over ``[arrival_time - duration,
    arrival_time]`` — the same "queued now, arrives after `duration`
    ms" model ``GameEngine.attempt_move`` uses to compute a
    ``PendingMove.arrival_time`` in the first place (*duration* isn't
    stored on ``PendingMove`` itself, so it's supplied separately here;
    pass ``cells_moved * move_duration``, the same expression
    ``attempt_move`` uses).

    Returns the earliest crossing time within the two moves' *overlapping*
    flight window, or ``None`` when:

    * the two flight windows don't overlap in time at all (one arrives
      before the other even starts), or
    * the paths never occupy the same point during the overlap (parallel
      paths with a constant non-zero offset, or paths whose rows and
      columns would coincide at different times), or
    * the paths *would* cross geometrically, but at a time outside the
      overlap — e.g. one piece has already landed by the time the other
      reaches that point.

    A non-``None`` result means the paths are at the same point at the
    same instant; it says nothing about whether that instant should
    matter to gameplay (whether the pieces are friendly/enemy, whether
    either is still selectable, etc.) — those decisions belong wherever
    this gets wired in, not here.

    Two straight lines parameterized by time are each an affine function
    of *t* per axis (``position(t) = start_pos + velocity * (t -
    start_time)``), so requiring both axes equal at the same *t* is two
    linear equations in one unknown: each axis either pins *t* to exactly
    one value, is trivially satisfied at every *t* (both paths share that
    axis's position and rate — e.g. two pieces moving along the same row),
    or is never satisfied (a constant non-zero gap on that axis). If both
    axes are trivially satisfied, the two paths coincide for the entire
    overlap, not just one instant — the overlap's start is returned as
    the (first) crossing time.
    """
    if duration_a <= 0:
        raise ValueError(f"duration_a must be positive, got {duration_a}")
    if duration_b <= 0:
        raise ValueError(f"duration_b must be positive, got {duration_b}")

    start_a = move_a.arrival_time - duration_a
    start_b = move_b.arrival_time - duration_b
    window_start = max(start_a, start_b)
    window_end = min(move_a.arrival_time, move_b.arrival_time)
    if window_start > window_end:
        return None  # never both in flight at once

    candidate: Optional[Fraction] = None
    axes = (
        (move_a.from_pos.row, move_a.to_pos.row, move_b.from_pos.row, move_b.to_pos.row),
        (move_a.from_pos.col, move_a.to_pos.col, move_b.from_pos.col, move_b.to_pos.col),
    )
    for p0_a, p1_a, p0_b, p1_b in axes:
        slope_a = Fraction(p1_a - p0_a, duration_a)
        slope_b = Fraction(p1_b - p0_b, duration_b)
        intercept_a = Fraction(p0_a) - slope_a * start_a
        intercept_b = Fraction(p0_b) - slope_b * start_b

        coeff = slope_a - slope_b
        const = intercept_a - intercept_b
        if coeff == 0:
            if const != 0:
                return None  # constant non-zero gap on this axis, forever
            continue  # this axis matches at every t -- no constraint from it

        axis_t = -const / coeff
        if candidate is not None and axis_t != candidate:
            return None  # row and col would only match at different times
        candidate = axis_t

    if candidate is None:
        # Neither axis constrained t: the two paths coincide at every
        # instant of the overlap, not just a single crossing point.
        return window_start
    if window_start <= candidate <= window_end:
        return candidate
    return None
