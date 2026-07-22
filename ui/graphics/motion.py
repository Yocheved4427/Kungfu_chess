from __future__ import annotations

from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from core.models import PendingMove

# ---------------------------------------------------------------------------
# Kung Fu Chess – Smooth movement interpolation
# ---------------------------------------------------------------------------
# Turns a PendingMove's per-cell checkpoint timing (see
# core.models.PendingMove.checkpoints, populated by
# engine.game.GameEngine.attempt_move/_build_checkpoints) into a
# continuous, sub-cell (row, col) position for rendering.
#
# This is purely a render-time visual: the engine's own board occupancy
# never leaves from_pos until the move actually resolves (a
# checkpoint-clear pass makes no board mutation at all — see
# GameEngine._resolve_checkpoint's own docstring), so nothing here
# affects gameplay, legality, or game state. Computed fresh every frame
# from the same absolute game-clock timestamps the engine itself already
# uses (GameSnapshot.current_time, PendingMove.start_time/arrival_time/
# checkpoints[*].due_time) — nothing new is stored anywhere for this.
# ---------------------------------------------------------------------------


def interpolate_position(pending_move: "PendingMove", current_time: int) -> Tuple[float, float]:
    """Return *pending_move*'s piece's current (row, col) as floats.

    *current_time* is the same absolute game-clock ms every other engine
    timestamp uses (``GameSnapshot.current_time``,
    ``PendingMove.arrival_time``, etc.) — not an offset relative to the
    move's own start.

    Finds the two waypoints — ``(from_pos, start_time)`` and each of
    ``checkpoints`` in turn, chronologically — bracketing *current_time*,
    and linearly interpolates between their cell positions by how far
    through that segment *current_time* falls (0.0 at the earlier
    waypoint's own time, 1.0 at the later one's). Clamped to the origin
    at or before ``start_time`` and to ``to_pos`` at or after
    ``arrival_time``, so a *current_time* slightly outside the move's own
    window (e.g. a snapshot taken a moment either side of it) degrades
    gracefully to one of the two endpoints instead of extrapolating off
    the path.
    """
    if current_time <= pending_move.start_time:
        return (float(pending_move.from_pos.row), float(pending_move.from_pos.col))
    if current_time >= pending_move.arrival_time:
        return (float(pending_move.to_pos.row), float(pending_move.to_pos.col))

    waypoints = [(pending_move.from_pos, pending_move.start_time)] + [
        (checkpoint.pos, checkpoint.due_time) for checkpoint in pending_move.checkpoints
    ]
    for (pos_a, t_a), (pos_b, t_b) in zip(waypoints, waypoints[1:]):
        if t_a <= current_time <= t_b:
            fraction = (current_time - t_a) / (t_b - t_a) if t_b > t_a else 0.0
            return (
                pos_a.row + (pos_b.row - pos_a.row) * fraction,
                pos_a.col + (pos_b.col - pos_a.col) * fraction,
            )

    # Unreachable for any PendingMove attempt_move() actually builds
    # (checkpoints[-1] is always (to_pos, arrival_time), already covered
    # by the clamp above) -- only possible for one built directly without
    # checkpoint data (e.g. in a test), where there's nothing to
    # interpolate through at all.
    return (float(pending_move.to_pos.row), float(pending_move.to_pos.col))
