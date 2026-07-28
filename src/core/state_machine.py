"""A piece's game-logic lifecycle state -- idle / moving / jumping / resting.

NEW module (no duplicated rules): ``engine.game.GameEngine`` already
exposes this exact information via three separate boolean queries
(``is_in_transit``, ``is_airborne``, ``is_in_cooldown`` -- see that
class's own ``_is_busy``, which combines all three the same way this
module does) against a live ``engine.game_state.GameState``. This is
purely a facade collapsing those three calls into one enum, for a
caller that wants "what is this piece doing right now" as a single
value rather than three separate booleans -- it reads engine/game_state
state, it never stores or computes anything itself.

Distinct from ``src.rendering.piece_state_machine.PieceStateMachine``,
which tracks a piece's current ANIMATION state (idle/move/jump/
short_rest/long_rest sprite sequences, driven by wall-clock time) --
that one is a rendering concern with no notion of game rules at all;
this one is a game-logic concern with no notion of pixels or sprites.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.game import GameEngine
    from engine.game_state import GameState
    from shared.models.cell import Cell

__all__ = ["PieceLifecycleState", "piece_lifecycle_state"]


class PieceLifecycleState(Enum):
    """What a piece is currently doing, per ``GameEngine``'s own
    busy/idle rules (see ``GameEngine._is_busy``)."""

    IDLE = auto()
    MOVING = auto()
    JUMPING = auto()
    RESTING = auto()


def piece_lifecycle_state(
    engine: "GameEngine", state: "GameState", position: "Cell"
) -> PieceLifecycleState:
    """The ``PieceLifecycleState`` of whatever's at *position* in *state*,
    as of right now -- queried fresh each call, never cached (a piece's
    state can change on the very next ``engine.tick()``).

    Checked in the same order ``GameEngine._is_busy`` combines them:
    in transit (a queued move hasn't arrived yet) beats airborne (mid-
    jump) beats cooling down (resting after a landing) beats idle --
    the first true "and its" wins, mirroring that method's own
    precedence, though in practice a piece can only ever be in one of
    these at a time.
    """
    if engine.is_in_transit(state, position):
        return PieceLifecycleState.MOVING
    if engine.is_airborne(state, position):
        return PieceLifecycleState.JUMPING
    if engine.is_in_cooldown(state, position):
        return PieceLifecycleState.RESTING
    return PieceLifecycleState.IDLE
