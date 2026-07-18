from __future__ import annotations

from typing import Dict, Optional, Set

from core.config import PIECE_POINTS
from core.models import Color, PendingJump, PendingMove, Position
from engine.geometry import is_diagonal, is_orthogonal
from engine.snapshot import BoardSnapshot, GameSnapshot

# ---------------------------------------------------------------------------
# Kung Fu Chess – Cumulative capture score
# ---------------------------------------------------------------------------
# Score is CUMULATIVE, based on captures, not a live recount of remaining
# material: when a piece is captured, the capturing player's score goes up
# by that piece's point value (PIECE_POINTS), and never decreases. A stateful,
# kept-alive-across-frames tracker, same idiom as ui.graphics.piece_view's
# PieceView -- it remembers the last GameSnapshot it saw and only reacts to
# what changed since then, rather than re-deriving anything from a single
# snapshot in isolation (there's no way to tell "did a capture just happen"
# from one snapshot alone).
#
# update() must be called once per frame, with every consecutive snapshot
# -- skipping a frame could skip over a capture happening between two
# snapshots ScoreTracker never saw consecutively.
#
# Lives in engine/, not core/ (core.models stays free of any engine
# import -- see engine.game_state's module docstring) and not ui/graphics/
# (this needs no rendering/asset machinery and no flat-sibling import
# setup; GameSnapshot is already an engine-layer type main_gui.py imports
# the normal package way).
#
# Detects two distinct ways GameEngine._resolve_due_move actually produces
# a capture (see that method's docstring):
#   1. A normal arrival, where the mover's token overwrites an enemy
#      token at the same cell -- see _score_overwrite_captures.
#   2. An airborne interception (AirborneCaptureEvent), where the
#      *arriving* piece is deleted from its own origin cell outright and
#      never appears at its destination at all -- the defender never
#      moves. A same-cell "before/after" diff cannot see this: nothing
#      appears anywhere to attribute the capture to. See
#      _score_airborne_captures for how this is reconstructed instead,
#      from the previous snapshot's pending/airborne lists.
# Pure move-shape math (is_orthogonal/is_diagonal) is imported from
# engine.geometry rather than re-derived, same as everywhere else in this
# codebase that needs it.
# ---------------------------------------------------------------------------


class ScoreTracker:
    """Cumulative per-colour capture score, kept alive across frames.

    ``get_score(color)`` starts at 0 for both colours and only ever goes
    up, by exactly ``PIECE_POINTS[captured piece's kind]`` per capture.
    """

    def __init__(self) -> None:
        self._scores: Dict[Color, int] = {Color.WHITE: 0, Color.BLACK: 0}
        self._previous: Optional[GameSnapshot] = None

    def get_score(self, color: Color) -> int:
        return self._scores[color]

    def update(self, snapshot: GameSnapshot) -> None:
        """Score every capture that happened since the last ``update()``
        call, by diffing *snapshot* against the one from last time.

        A no-op the first time it's called (nothing to diff against
        yet) -- matching ``PieceView.sync()``'s handling of a
        freshly-created view with no previous snapshot.
        """
        previous = self._previous
        self._previous = snapshot
        if previous is None:
            return

        self._score_overwrite_captures(previous.board, snapshot.board)
        self._score_airborne_captures(previous, snapshot)

    def _score_overwrite_captures(
        self, previous_board: BoardSnapshot, current_board: BoardSnapshot
    ) -> None:
        """Score every cell where a piece present last snapshot has been
        replaced by an opposing-colour piece this snapshot -- an ordinary
        move landing on an enemy. Runs over the whole board every call
        (not just one cell), so several captures resolved within the
        same ``tick()`` are all counted, not just the first.

        A same-colour kind change (e.g. Pawn -> Queen) is a promotion,
        not a capture -- excluded by the ``color`` comparison below,
        since promotion never changes ``color``.
        """
        for row in range(previous_board.num_rows):
            for col in range(previous_board.num_cols):
                pos = Position(row=row, col=col)
                before = previous_board.get_piece_at(pos)
                if before is None:
                    continue
                after = current_board.get_piece_at(pos)
                if after is not None and after.color != before.color:
                    self._scores[after.color] += PIECE_POINTS[before.kind]

    def _score_airborne_captures(self, previous: GameSnapshot, current: GameSnapshot) -> None:
        """Score every previously-queued move that just resolved as an
        airborne interception rather than a normal arrival.

        A ``PendingMove`` that was pending last snapshot and no longer is
        this snapshot was resolved somehow this tick. It's specifically
        an airborne-interception capture only if ALL of:

        * ``current`` still has no piece at all at ``pm.from_pos`` --
          rules out the move having been dropped because its own piece
          was captured *elsewhere*, at its origin, by something else
          entirely (that's a different, unrelated capture, already
          scored by ``_score_overwrite_captures`` -- if a piece now
          occupies ``pm.from_pos``, that's what happened, and crediting
          an airborne defender too would double-count).
        * an enemy ``PendingJump`` was defending ``pm.to_pos`` as of
          ``previous`` -- the only way ``_resolve_due_move`` actually
          deletes an arriving piece outright instead of moving or
          dropping it.
        * ``pm.piece`` isn't findable anywhere between (and including)
          ``pm.from_pos`` and ``pm.to_pos`` in ``current`` -- rules out a
          friendly-block stop-short (the piece relocates to a cell on
          its own path, it isn't deleted), which is unrelated to whether
          ``pm.to_pos`` happens to also hold an airborne enemy.

        Piece identity here is by token + position only, same limitation
        as everywhere else in this engine (no persistent per-piece ID) --
        see ``GraphicsBoardRenderer._sync_piece_views``'s docstring for
        the same caveat on the rendering side.
        """
        resolved: Set[PendingMove] = set(previous.pending) - set(current.pending)
        for pm in resolved:
            if current.board.get_piece_at(pm.from_pos) is not None:
                continue

            defender = self._airborne_defender_at(pm.to_pos, pm.piece, previous.airborne)
            if defender is None:
                continue

            if self._piece_found_along_its_path(pm, current.board):
                continue

            defender_color = Color.WHITE if defender.piece[0] == Color.WHITE.value else Color.BLACK
            self._scores[defender_color] += PIECE_POINTS[pm.piece[1]]

    @staticmethod
    def _airborne_defender_at(
        pos: Position, attacker_piece: str, airborne: "tuple[PendingJump, ...]"
    ) -> Optional[PendingJump]:
        """The ``PendingJump`` defending *pos*, iff it's an enemy of
        *attacker_piece* -- same rule as
        ``CollisionResolver.airborne_defender``, reimplemented here
        rather than called: that method takes a live ``AbstractBoard``
        collaborator and is reached only via ``GameEngine.tick()``'s real
        pipeline, not something this read-only, board-less diff should
        depend on."""
        for pj in airborne:
            if pj.pos == pos and pj.piece[0] != attacker_piece[0]:
                return pj
        return None

    @staticmethod
    def _piece_found_along_its_path(pm: PendingMove, board: BoardSnapshot) -> bool:
        """True if *pm*'s piece can still be found at its origin,
        destination, or (for a straight-line move) any cell strictly
        between them in *board*.

        Mirrors ``CollisionResolver.stop_before_friendly_block``'s own
        path-walking: a Knight's L-shape (or any non-orthogonal,
        non-diagonal move) has no intermediate cell at all, so only its
        two endpoints are checked.
        """
        cells = [pm.from_pos, pm.to_pos]
        if is_orthogonal(pm.from_pos, pm.to_pos) or is_diagonal(pm.from_pos, pm.to_pos):
            dr = pm.to_pos.row - pm.from_pos.row
            dc = pm.to_pos.col - pm.from_pos.col
            steps = max(abs(dr), abs(dc))
            step_r, step_c = dr // steps, dc // steps
            r, c = pm.from_pos.row + step_r, pm.from_pos.col + step_c
            while (r, c) != (pm.to_pos.row, pm.to_pos.col):
                cells.append(Position(r, c))
                r += step_r
                c += step_c

        for cell in cells:
            piece = board.get_piece_at(cell)
            if piece is not None and piece.color.value + piece.kind == pm.piece:
                return True
        return False
