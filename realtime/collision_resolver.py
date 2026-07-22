from __future__ import annotations

from typing import List

from core.models import PendingJump, PendingMove, Position, same_color
from engine.board import AbstractBoard
from engine.geometry import is_diagonal, is_orthogonal

# ---------------------------------------------------------------------------
# Kung Fu Chess – Collision Resolver
# ---------------------------------------------------------------------------
# Extracted out of GameEngine.tick() (SRP): the two pieces of "what happens
# when a due move meets the board's *current* occupants" logic that don't
# belong to plain move legality (MoveValidator's job) or clock/queue
# bookkeeping (GameEngine's job) — friendly mid-route blocking, and
# airborne-enemy interception.
#
# Stateless, same idiom as MoveValidator / RuleEngine / GameOverRule
# elsewhere in this codebase: constructed once with no board reference of
# its own, and given whatever state it needs (board, the airborne list) as
# call arguments. GameEngine remains the sole board mutator and the only
# component that fires events — this class only *decides*, it never
# touches ``board`` or notifies observers.
# ---------------------------------------------------------------------------


class CollisionResolver:
    """Resolves route-blocking and airborne-interception outcomes for a
    due ``PendingMove`` against the board's current state."""

    def path_cells(self, from_pos: Position, to_pos: Position) -> List[Position]:
        """Return the ordered list of cells strictly between *from_pos*
        and *to_pos* on a straight line (orthogonal or diagonal) —
        excludes both endpoints, nearest-to-``from_pos`` first. Empty
        for a non-straight-line move (e.g. a Knight's jump) or adjacent
        cells (no intermediate square at all).

        Pure geometry, no board access — shared by
        ``stop_before_friendly_block`` (walks this list checking
        occupancy at each cell in one shot) and ``GameEngine``'s per-move
        checkpoint computation (each cell becomes its own individually
        timed waypoint — see ``core.models.PendingMove.checkpoints``).
        """
        if not (is_orthogonal(from_pos, to_pos) or is_diagonal(from_pos, to_pos)):
            return []

        dr = to_pos.row - from_pos.row
        dc = to_pos.col - from_pos.col
        steps = max(abs(dr), abs(dc))
        if steps < 2:
            return []  # adjacent cells have no square between them

        step_r = dr // steps
        step_c = dc // steps
        cells: List[Position] = []
        r, c = from_pos.row + step_r, from_pos.col + step_c
        while (r, c) != (to_pos.row, to_pos.col):
            cells.append(Position(r, c))
            r += step_r
            c += step_c
        return cells

    def is_friendly_occupied(self, pos: Position, piece: str, board: AbstractBoard) -> bool:
        """True iff *pos* is currently occupied by a piece of the same
        colour as *piece*.

        The single-cell version of the per-cell occupancy+colour check
        ``stop_before_friendly_block`` performs while walking a whole
        path in one shot — used by ``GameEngine`` to check one specific
        checkpoint at its own due time instead of only at the end of the
        move (see ``GameEngine._resolve_checkpoint``).
        """
        return same_color(board.get_piece_at(pos), piece)

    def stop_before_friendly_block(
        self, pm: PendingMove, board: AbstractBoard
    ) -> Position | None:
        """Where a due move should stop short, if a friendly piece is now
        blocking its route — or None if that doesn't apply.

        Only meaningful for a straight-line, multi-cell move (orthogonal
        or diagonal); anything else (a Knight's jump, a single-step move
        with no intermediate square) returns None immediately. Walks the
        cells strictly between ``pm.from_pos`` and ``pm.to_pos``:

        * Path fully clear -> None (normal ``is_valid`` handling decides
          the outcome, same as before this rule existed).
        * First occupied cell holds an enemy piece -> None (an enemy
          mid-route is still a fully-dropped premove, via the ordinary
          path-clear check in ``MoveValidator.is_valid``).
        * First occupied cell holds a friendly piece -> the last clear
          cell before it (which is ``pm.from_pos`` itself if that very
          first step is already blocked — the piece simply doesn't move).
        """
        prev = pm.from_pos
        for cell in self.path_cells(pm.from_pos, pm.to_pos):
            occupant = board.get_piece_at(cell)
            if occupant != ".":
                return prev if same_color(occupant, pm.piece) else None
            prev = cell
        return None  # path fully clear

    def airborne_defender(
        self, pos: Position, attacker: str, airborne: List[PendingJump]
    ) -> PendingJump | None:
        """Return the ``PendingJump`` defending *pos*, iff it belongs to
        the opposite colour of *attacker* — i.e. it intercepts *attacker*
        arriving there. None if nothing is airborne at *pos*, or if it's
        a friendly piece (a friendly arrival is already rejected earlier
        by the ordinary friendly-fire check in ``MoveValidator.is_valid``,
        so that case never reaches here in practice)."""
        for pj in airborne:
            if pj.pos == pos:
                return pj if pj.piece[0] != attacker[0] else None
        return None
