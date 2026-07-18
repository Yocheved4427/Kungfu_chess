from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.snapshot import GameSnapshot

# ---------------------------------------------------------------------------
# Kung Fu Chess – Game-over screen animation
# ---------------------------------------------------------------------------
# Tracks real wall-clock elapsed time since GameSnapshot.game_over first
# became True, the same idiom as PieceStateMachine's own _entered_at /
# time.time() timing (see ui.graphics.piece_state_machine) — deliberately
# NOT GameSnapshot.current_time (the game clock), so this animation reads
# smoothly in real time regardless of how the game clock itself is
# driven, matching every other animation in this codebase.
#
# game_over is a one-way flag — GameEngine._check_game_over is a no-op
# once state.game_over is already True (see that method's own docstring)
# — so this only ever needs to catch the FIRST True, not a general
# False<->True transition like PieceView/ScoreTracker's snapshot diffing.
# ---------------------------------------------------------------------------

FADE_DURATION_SEC = 1.0


class GameOverAnimation:
    """Tracks the game-over overlay's fade-in progress, from the moment
    ``GameSnapshot.game_over`` first turns True.

    ``progress()`` is 0.0 before the game has ended, rises to 1.0 over
    ``FADE_DURATION_SEC`` seconds of real time after that, and stays
    pinned at 1.0 forever afterward — it never resets or loops, so the
    game-over screen stays fully visible once it's finished animating in
    (the game has ended; the message should stay up).
    """

    def __init__(self) -> None:
        self._entered_at: "float | None" = None

    @property
    def is_active(self) -> bool:
        """True from the moment the game first ended, forever after."""
        return self._entered_at is not None

    def sync(self, snapshot: "GameSnapshot") -> None:
        """Start the animation the first time *snapshot* reports
        ``game_over`` — a no-op on every call after that (including
        every call before the game ends)."""
        if snapshot.game_over and self._entered_at is None:
            self._entered_at = time.time()

    def progress(self) -> float:
        """0.0 if the game hasn't ended yet; otherwise the fraction of
        ``FADE_DURATION_SEC`` elapsed since it did, clamped to ``[0, 1]``."""
        if self._entered_at is None:
            return 0.0
        elapsed = time.time() - self._entered_at
        return min(elapsed / FADE_DURATION_SEC, 1.0)
