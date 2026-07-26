from __future__ import annotations

from typing import Dict

from shared.models.cell import Cell

# ---------------------------------------------------------------------------
# Kung Fu Chess – Cooldown
# ---------------------------------------------------------------------------
# Pure state logic, extracted out of GameEngine.is_in_cooldown/
# _set_cooldown so it has exactly one home. GameEngine still owns
# *when* a cooldown starts (on a landing — a move's arrival, a
# friendly-block stop-short, or a jump grounding) and still owns
# ``GameState.cooldowns`` itself; it just calls through to the
# functions here instead of repeating the ``{Cell: expiry_time_ms}``
# arithmetic inline. This also lets server/game (a facade layer over
# engine/) re-expose the same, single implementation instead of a
# second copy.
# ---------------------------------------------------------------------------


def is_resting(cooldowns: Dict[Cell, int], pos: Cell, current_time: int) -> bool:
    """True iff *pos* is still cooling down at *current_time*, per
    *cooldowns* (shaped exactly like ``GameState.cooldowns``). Expires
    on its own once ``current_time`` passes the stored expiry — no
    explicit cleanup is needed.
    """
    expiry = cooldowns.get(pos)
    return expiry is not None and expiry > current_time


def start_cooldown(
    cooldowns: Dict[Cell, int], pos: Cell, current_time: int, duration: int
) -> None:
    """Start (or restart) *pos*'s cooldown window in *cooldowns*, from
    *current_time*, lasting *duration* ms. Mutates *cooldowns* in
    place, same as ``GameEngine._set_cooldown`` always has.
    """
    cooldowns[pos] = current_time + duration
