from __future__ import annotations

from typing import Optional, Sequence, Tuple

from shared.models.cell import Cell
from core.models import PendingMove, same_color

# ---------------------------------------------------------------------------
# Kung Fu Chess – Route Lock
# ---------------------------------------------------------------------------
# Pure logic, extracted out of GameEngine's own _lane/_route_conflicts
# methods so it has exactly one home — same pattern already used for
# engine.geometry/engine.cooldown/engine.promotion: GameEngine still
# owns applying the result (attempt_move rejecting a move), it just
# calls through to the functions here instead of keeping the lane/
# overlap arithmetic inline as private methods. GameEngine._lane stays
# in place as a thin staticmethod delegate (existing tests call it
# directly, e.g. tests/unit/test_realtime_conflicts.py), so nothing
# calling it needs to change.
#
# "Opposite-colour pieces may not travel a common route (the same span
# of columns on a horizontal move, or rows on a vertical move) at the
# same time" — the rule GameEngine.attempt_move enforces via
# has_route_conflict, below.
# ---------------------------------------------------------------------------

Lane = Tuple[str, int, int]  # (axis, lo, hi) -- axis is "row" or "col"


def lane(from_pos: Cell, to_pos: Cell) -> Optional[Lane]:
    """The (axis, lo, hi) lane a straight move travels through.

    A horizontal move occupies every column between *from_pos* and
    *to_pos* on its row; a vertical move occupies every row on its
    column. Diagonal / knight moves don't travel a single-axis lane
    and return None — they never participate in route locking.
    """
    if from_pos.row == to_pos.row and from_pos.col != to_pos.col:
        lo, hi = sorted((from_pos.col, to_pos.col))
        return ("col", lo, hi)
    if from_pos.col == to_pos.col and from_pos.row != to_pos.row:
        lo, hi = sorted((from_pos.row, to_pos.row))
        return ("row", lo, hi)
    return None


def has_route_conflict(
    pending: Sequence[PendingMove], piece: str, from_pos: Cell, to_pos: Cell
) -> bool:
    """True iff a move of *piece* from *from_pos* to *to_pos* would
    share a lane with an opposite-colour move already in *pending*.

    Opposite-colour pieces may not travel a common route (the same
    span of columns on a horizontal move, or rows on a vertical move)
    at the same time — the second mover is rejected. Same-colour moves
    and non-lane moves (diagonal / knight) never conflict.
    """
    this_lane = lane(from_pos, to_pos)
    if this_lane is None:
        return False
    axis, lo, hi = this_lane
    for pm in pending:
        if same_color(pm.piece, piece):
            continue
        other_lane = lane(pm.from_pos, pm.to_pos)
        if other_lane is None:
            continue
        other_axis, other_lo, other_hi = other_lane
        if other_axis != axis:
            continue
        if lo <= other_hi and other_lo <= hi:
            return True
    return False
