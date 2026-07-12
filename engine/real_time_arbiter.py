from __future__ import annotations

from dataclasses import dataclass
from typing import List

from core.models import Position

# ---------------------------------------------------------------------------
# Kung Fu Chess – Real-Time Arbiter
# ---------------------------------------------------------------------------
# Tracks in-progress, timed moves against a virtual clock. There is no
# wall-clock time anywhere in this class — time only ever moves forward
# when a caller explicitly calls advance_time(ms). That's what makes it
# deterministic: replaying the same sequence of advance_time() calls
# always produces the same result, and tests never need (or should use)
# time.sleep() to simulate elapsed time — just call
# arbiter.advance_time(1000) instead.
#
# Scope: pure scheduling/bookkeeping. This class decides WHEN a move is
# due; it never decides whether a move is legal (RuleEngine's job) or
# applies one to a board (GameEngine's job — the single service layer
# that owns board state, per engine.game.GameEngine's own docstring).
# RealTimeArbiter never touches a Board and has no board reference.
#
# GameEngine's own current_time / _pending (see tick()) already implement
# this same idea inline, purpose-built for the real gameplay pipeline
# (which also does re-validation, promotion, jump interception, etc. on
# arrival). RealTimeArbiter is a standalone, directly-testable
# formalization of just the timing/scheduling piece of that — not (yet)
# wired into GameEngine.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActiveMove:
    """A snapshot of one in-progress move at the moment it was read.

    ``remaining_ms`` is always >= 0. A move is reported back to the
    caller (via ``advance_time``'s return value) with ``remaining_ms``
    pinned to 0 the instant it becomes due — at that point the arbiter
    stops tracking it internally.
    """
    piece: str
    from_pos: Position
    to_pos: Position
    remaining_ms: int


@dataclass(frozen=True)
class _ScheduledMove:
    """Internal bookkeeping entry — stores an absolute arrival time
    rather than a relative remaining time, so nothing has to be rewritten
    as the clock advances; only ``ActiveMove`` snapshots are relative."""
    piece: str
    from_pos: Position
    to_pos: Position
    arrival_time: int


class RealTimeArbiter:
    """Deterministic, virtual-clock-driven scheduler for in-progress moves.

    Usage
    -----
    * ``start_move(piece, from_pos, to_pos, duration_ms)`` registers a
      move that will be due ``duration_ms`` from the current virtual time.
    * ``advance_time(ms)`` moves the virtual clock forward by *ms* and
      returns every move that became due as a result (chronological
      order — earliest arrival first, ties keep registration order),
      removing them from internal tracking.
    * ``active_moves`` is a read-only snapshot of everything still in
      progress, each annotated with its current remaining travel time.
    """

    def __init__(self) -> None:
        self._current_time: int = 0
        self._scheduled: List[_ScheduledMove] = []

    @property
    def current_time(self) -> int:
        """The virtual clock's current value, in milliseconds."""
        return self._current_time

    @property
    def active_moves(self) -> List[ActiveMove]:
        """Every move still in progress, with its remaining travel time
        computed as of right now. A fresh snapshot on every call."""
        return [
            ActiveMove(
                piece=entry.piece,
                from_pos=entry.from_pos,
                to_pos=entry.to_pos,
                remaining_ms=entry.arrival_time - self._current_time,
            )
            for entry in self._scheduled
        ]

    def start_move(
        self, piece: str, from_pos: Position, to_pos: Position, duration_ms: int
    ) -> None:
        """Register a move that becomes due ``duration_ms`` from now."""
        if duration_ms < 0:
            raise ValueError(f"duration_ms must be >= 0, got {duration_ms}")
        self._scheduled.append(
            _ScheduledMove(
                piece=piece,
                from_pos=from_pos,
                to_pos=to_pos,
                arrival_time=self._current_time + duration_ms,
            )
        )

    def is_moving(self, pos: Position) -> bool:
        """True iff *pos* is the origin of a move still in progress."""
        return any(entry.from_pos == pos for entry in self._scheduled)

    def cancel_move(self, from_pos: Position) -> bool:
        """Stop tracking the in-progress move originating at *from_pos*
        (e.g. its piece was removed by some other means mid-flight).

        Returns True iff a move was actually found and cancelled.
        """
        for entry in self._scheduled:
            if entry.from_pos == from_pos:
                self._scheduled.remove(entry)
                return True
        return False

    def advance_time(self, ms: int) -> List[ActiveMove]:
        """Move the virtual clock forward by *ms* milliseconds.

        Never sleeps, never touches wall-clock time — this is the sole
        way time passes for this arbiter, and it's entirely synchronous
        and deterministic: call it with whatever ms value a test wants
        to simulate, and the result is 100% reproducible.

        Returns every move whose arrival time is now due
        (``arrival_time <= current_time``), sorted chronologically
        (earliest arrival first; ties keep registration order) — each
        reported with ``remaining_ms == 0``. Those moves are no longer
        tracked afterward; everything else remains in ``active_moves``
        with its remaining time reduced accordingly.
        """
        if ms < 0:
            raise ValueError(f"ms must be >= 0, got {ms}")
        self._current_time += ms

        due = [e for e in self._scheduled if e.arrival_time <= self._current_time]
        due.sort(key=lambda e: e.arrival_time)
        self._scheduled = [
            e for e in self._scheduled if e.arrival_time > self._current_time
        ]

        return [
            ActiveMove(piece=e.piece, from_pos=e.from_pos, to_pos=e.to_pos, remaining_ms=0)
            for e in due
        ]
