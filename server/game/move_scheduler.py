from __future__ import annotations

from typing import Dict

from shared.models.cell import Cell
from engine.cooldown import is_resting, start_cooldown

# ---------------------------------------------------------------------------
# Kung Fu Chess – Server Move Scheduler (facade)
# ---------------------------------------------------------------------------
# Thin facade over engine.cooldown — the actual cooldown state
# ({Cell: expiry_time_ms}) and its arithmetic (start a window; ask
# whether one is still open) already exist, and are already the single
# implementation GameEngine.is_in_cooldown/_set_cooldown themselves
# call (see engine/cooldown.py's own docstring). This module re-exposes
# that under server/game's naming, plus one convenience: a
# fixed-duration MoveScheduler that a caller doesn't have to keep
# passing its own cooldown length into on every call.
# ---------------------------------------------------------------------------


class MoveScheduler:
    """Tracks, per cell, whether the piece there is still resting
    (cooling down) after its last landing, and restricted from moving.

    Holds no board/game reference of its own — same idiom as
    ``engine.rules.MoveValidator``/``engine.rule_engine.RuleEngine``:
    constructed once (with the game's fixed cooldown duration), then
    given whatever ``cooldowns`` mapping it needs as a call argument —
    typically ``GameState.cooldowns`` straight from the caller's own
    game state.
    """

    def __init__(self, cooldown_duration_ms: int) -> None:
        self._cooldown_duration_ms = cooldown_duration_ms

    def is_resting(
        self, cooldowns: Dict[Cell, int], pos: Cell, current_time_ms: int
    ) -> bool:
        """True iff the piece at *pos* is still cooling down at
        *current_time_ms*, and so restricted from moving — per
        *cooldowns*, shaped exactly like ``GameState.cooldowns``.
        """
        return is_resting(cooldowns, pos, current_time_ms)

    def start_cooldown(
        self, cooldowns: Dict[Cell, int], pos: Cell, current_time_ms: int
    ) -> None:
        """Start (or restart) *pos*'s cooldown window in *cooldowns*,
        from *current_time_ms*, lasting this scheduler's own
        ``cooldown_duration_ms``. Mutates *cooldowns* in place.
        """
        start_cooldown(cooldowns, pos, current_time_ms, self._cooldown_duration_ms)
