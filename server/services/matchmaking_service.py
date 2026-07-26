from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional

# ---------------------------------------------------------------------------
# Kung Fu Chess – Matchmaking Service
# ---------------------------------------------------------------------------
# ELO-based matchmaking queue and pairing — there was no matchmaking
# concept anywhere in this codebase before this (server/server.py's own
# module docstring calls it out explicitly as "a later task").
# UserRecord.elo_rating (server/database/sqlite_db_manager.py) already
# exists and is fully persisted, just never consulted by anything until
# now.
#
# Knows nothing about sockets, rooms, or chess itself — pure in-memory
# queue bookkeeping, given each player's ELO by its caller (typically
# read from AuthService's own AuthResult.user.elo_rating) rather than
# looking it up itself. Not thread-safe on its own — same caveat as
# RoomService; server/network/server.py serializes its own access.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QueueEntry:
    """One player waiting for an opponent."""
    username: str
    elo_rating: int
    queued_at: float  # time.monotonic() seconds


@dataclass(frozen=True)
class MatchPairing:
    """Two players ``MatchmakingService.find_match`` paired up and
    removed from the queue. Carries no colour assignment — that's the
    caller's own call (see server/network/server.py)."""
    player_a: QueueEntry
    player_b: QueueEntry


class MatchmakingService:
    """FIFO queue of players wanting an opponent, paired by ELO
    closeness.

    The longer a player waits, the wider an ELO gap this service will
    accept for them (``base_elo_range`` widening by
    ``range_growth_per_second`` for every second queued) — so a player
    at the edge of the pool's rating distribution still eventually
    gets matched, instead of waiting forever for a near-exact ELO match
    that may never arrive.
    """

    def __init__(
        self,
        base_elo_range: int = 100,
        range_growth_per_second: float = 10.0,
    ) -> None:
        self._base_elo_range = base_elo_range
        self._range_growth_per_second = range_growth_per_second
        self._queue: List[QueueEntry] = []

    def enqueue(
        self, username: str, elo_rating: int, queued_at: Optional[float] = None
    ) -> None:
        """Add *username* to the queue, iff not already in it — a
        second ``enqueue`` for an already-queued username is a silent
        no-op; it does not reset their wait time.
        """
        if self.is_queued(username):
            return
        self._queue.append(
            QueueEntry(
                username=username,
                elo_rating=elo_rating,
                queued_at=queued_at if queued_at is not None else time.monotonic(),
            )
        )

    def dequeue(self, username: str) -> bool:
        """Remove *username* from the queue (e.g. they disconnected or
        cancelled). Returns True iff they were actually queued."""
        for i, entry in enumerate(self._queue):
            if entry.username == username:
                del self._queue[i]
                return True
        return False

    def is_queued(self, username: str) -> bool:
        return any(entry.username == username for entry in self._queue)

    def find_match(self, current_time: Optional[float] = None) -> Optional[MatchPairing]:
        """Find and remove the first pair of queued players whose ELO
        gap is within both players' currently-allowed range.

        Scans queued players in FIFO order, checking each against
        every later-queued player — so the longest-waiting player is
        always considered first — but a pairing only happens once BOTH
        sides' widened range covers the actual gap between them (a
        long-waiting player with a wide range still won't be paired
        against someone whose own, still-narrow range rejects the
        gap). Returns ``None`` if no such pair exists yet.
        """
        now = current_time if current_time is not None else time.monotonic()
        for i, a in enumerate(self._queue):
            range_a = self._allowed_range(a, now)
            for b in self._queue[i + 1:]:
                range_b = self._allowed_range(b, now)
                gap = abs(a.elo_rating - b.elo_rating)
                if gap <= range_a and gap <= range_b:
                    self._queue.remove(a)
                    self._queue.remove(b)
                    return MatchPairing(a, b)
        return None

    def _allowed_range(self, entry: QueueEntry, now: float) -> float:
        waited = max(0.0, now - entry.queued_at)
        return self._base_elo_range + waited * self._range_growth_per_second
