from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional

from shared.models.board import AbstractBoard
from shared.models.cell import Cell
from core.models import PendingJump
from realtime.collision_resolver import CollisionResolver

# ---------------------------------------------------------------------------
# Kung Fu Chess – Server Collision Service (facade)
# ---------------------------------------------------------------------------
# Thin facade over realtime.collision_resolver.CollisionResolver — the
# existing, single implementation of both decisions a converging-move
# needs (friendly mid-route blocking, airborne-enemy interception).
# This class doesn't re-derive either; it composes them into one call
# the same way engine.game.GameEngine._resolve_checkpoint already does
# inline (see that method's own docstring for the exact ordering this
# mirrors: within one tick, the earliest-due checkpoint across ALL
# pending moves is resolved first — so when two pieces race for the
# same square, whichever arrives first occupies it, and a
# later-arriving enemy can still capture it there while a
# later-arriving friendly is rejected as blocked).
# ---------------------------------------------------------------------------


class ArrivalOutcome(Enum):
    """What happens when a moving piece reaches — or is stopped before
    reaching — a cell along its route, decided against the board's
    CURRENT occupants (which may have changed since the move was
    queued: another piece could have moved there, or jumped, since).
    """
    LANDS = auto()                       # arrives cleanly at the checkpoint cell
    STOPPED_BY_FRIENDLY = auto()         # stops short: a friendly now blocks the route
    CAPTURES_AIRBORNE_DEFENDER = auto()  # arrives and defeats a jumping enemy defending the cell


@dataclass(frozen=True)
class ArrivalResolution:
    """Result of ``CollisionService.resolve_arrival``."""
    outcome: ArrivalOutcome
    landing_cell: Cell
    defeated_defender: Optional[PendingJump] = None


class CollisionService:
    """Resolves what happens when a real-time move reaches a cell that
    another piece may also occupy or be converging on.

    Holds no board reference of its own — same idiom as
    ``engine.rules.MoveValidator``/``engine.rule_engine.RuleEngine``:
    constructed once, given whatever board/airborne-list it needs as
    call arguments.
    """

    def __init__(self, collision_resolver: Optional[CollisionResolver] = None) -> None:
        self._collision_resolver: CollisionResolver = (
            collision_resolver if collision_resolver is not None else CollisionResolver()
        )

    def resolve_arrival(
        self,
        piece: str,
        checkpoint_pos: Cell,
        previous_cell: Cell,
        is_final_checkpoint: bool,
        board: AbstractBoard,
        airborne: List[PendingJump],
    ) -> ArrivalResolution:
        """Decide the outcome of *piece* reaching *checkpoint_pos* right
        now, given the move hasn't yet been dropped/landed.

        * A non-final checkpoint occupied by a friendly -> stops at
          *previous_cell* (the caller's own previous checkpoint, or the
          move's origin for the very first checkpoint — mirroring
          ``GameEngine._resolve_checkpoint``'s own stop-short rule,
          which this does not re-derive, only reports).
        * A final checkpoint defended by an airborne enemy -> that
          defender is defeated; the mover never actually lands there
          (see ``AirborneCaptureEvent``'s own semantics).
        * Otherwise -> lands cleanly at *checkpoint_pos*.

        Path-clear/shape legality is not this class's concern (that's
        ``MoveValidator``/``RuleEngine``'s job, checked once, at the
        final checkpoint) — this only classifies what a piece that is
        already en route encounters at one specific cell.
        """
        if not is_final_checkpoint:
            if self._collision_resolver.is_friendly_occupied(checkpoint_pos, piece, board):
                return ArrivalResolution(ArrivalOutcome.STOPPED_BY_FRIENDLY, previous_cell)
            return ArrivalResolution(ArrivalOutcome.LANDS, checkpoint_pos)

        defender = self._collision_resolver.airborne_defender(checkpoint_pos, piece, airborne)
        if defender is not None:
            return ArrivalResolution(
                ArrivalOutcome.CAPTURES_AIRBORNE_DEFENDER, checkpoint_pos, defender
            )
        return ArrivalResolution(ArrivalOutcome.LANDS, checkpoint_pos)

    def path_cells(self, from_cell: Cell, to_cell: Cell) -> List[Cell]:
        """Ordered cells strictly between *from_cell* and *to_cell* — see
        ``CollisionResolver.path_cells`` (this is a direct pass-through)."""
        return self._collision_resolver.path_cells(from_cell, to_cell)
