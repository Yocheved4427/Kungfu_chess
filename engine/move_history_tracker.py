from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from core.models import Color, PendingMove, Position
from engine.snapshot import GameSnapshot, PieceSnapshot

# ---------------------------------------------------------------------------
# Kung Fu Chess – Move history (for the GUI's history panel)
# ---------------------------------------------------------------------------
# A stateful, kept-alive-across-frames tracker, same idiom as
# ui.graphics.piece_view's PieceView and engine.score_tracker's
# ScoreTracker: it remembers the last GameSnapshot it saw and only reacts
# to what changed since then -- there's no way to tell "did a move just
# land" from a single snapshot in isolation.
#
# update() must be called once per frame, with every consecutive snapshot
# -- skipping a frame could skip over a move landing between two
# snapshots this tracker never saw consecutively.
#
# Lives in engine/, not core/ (core.models stays free of any engine
# import -- see engine.game_state's module docstring) and not
# ui/graphics/ (this needs no rendering/asset machinery and no
# flat-sibling import setup; GameSnapshot is already an engine-layer type
# main_gui.py imports the normal package way) -- same reasoning as
# ScoreTracker's own module docstring.
#
# "Completed" here means genuinely landed, not merely vanished from
# GameState.pending -- see GameEngine._resolve_due_move's own docstring
# for the full branching a PendingMove can take (dropped as invalid,
# stopped short by a friendly block, intercepted by an airborne
# defender, or actually arriving). _detect_completed_moves distinguishes
# these the same way ScoreTracker._score_airborne_captures does: by
# checking what's actually on the board at the move's origin and
# destination in the new snapshot, not just whether the PendingMove
# itself is still around.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompletedMove:
    """One successfully-completed move, recorded for the history panel.

    ``time``         – game clock (ms) at the moment the move completed
                       (the ``PendingMove``'s own ``arrival_time`` — not
                       *current*'s ``current_time``, which is when this
                       tracker noticed, potentially later than several
                       moves' own distinct arrival times if more than
                       one resolved within the same ``tick()`` call).
    ``color``        – the mover's ``Color``.
    ``kind``         – the piece-type char the mover LANDED as -- for an
                       ordinary move this is unchanged from what left
                       the origin, but for a promoting Pawn it's "Q"
                       (the piece now actually on the board), not "P"
                       (what it was before moving). Recorded this way so
                       ``kind`` + ``destination`` together always
                       describe what's really sitting on the board now.
    ``destination``  – the cell the move landed on.
    """

    time: int
    color: Color
    kind: str
    destination: Position


class MoveHistoryTracker:
    """Growing, in-memory log of completed moves, kept alive across frames.

    ``moves`` is the full history so far, oldest first — nothing is ever
    removed. No database or other persistence beyond this process; the
    task this exists for only asked for an in-memory session log.
    """

    def __init__(self) -> None:
        self._previous: Optional[GameSnapshot] = None
        self.moves: List[CompletedMove] = []

    def update(self, snapshot: GameSnapshot) -> None:
        """Record every move that completed since the last ``update()``
        call, by diffing *snapshot* against the one from last time.

        A no-op the first time it's called (nothing to diff against
        yet) -- matching ``PieceView.sync()``/``ScoreTracker.update()``'s
        handling of a freshly-created tracker with no previous snapshot.
        """
        previous = self._previous
        self._previous = snapshot
        if previous is None:
            return

        self.moves.extend(self._detect_completed_moves(previous, snapshot))

    def _detect_completed_moves(
        self, previous: GameSnapshot, current: GameSnapshot
    ) -> List[CompletedMove]:
        """Return a ``CompletedMove`` for each ``PendingMove`` that was
        pending as of *previous* and has genuinely landed as of
        *current*.

        A move counts as landed iff, in *current*:

        * its origin no longer holds a piece matching the mover -- rules
          out "dropped as invalid" (``MoveValidator.is_valid`` failed at
          resolution time), where the piece never leaves at all, and
        * its destination holds a piece of the mover's own colour whose
          kind matches the mover's -- or, promotion's one exception, is
          a Queen where the mover was a Pawn.

        This also correctly excludes a friendly-block stop-short (the
        piece relocates to a cell short of ``to_pos``, so ``to_pos``
        itself won't hold it) and an airborne interception (the piece is
        deleted outright, appearing nowhere) without needing to check
        for those cases specifically — neither leaves the mover's own
        colour/kind sitting at ``to_pos``.

        Processed in the same order ``GameEngine.tick()`` itself would
        have applied them (earliest ``arrival_time`` first, ties broken
        by *previous.pending*'s own order — see ``tick()``'s own
        docstring) so several moves completing in the same tick are
        recorded in a deterministic, chronologically-accurate order,
        not whatever order an unordered set diff happens to produce.
        """
        previous_order: Dict[PendingMove, int] = {
            pm: i for i, pm in enumerate(previous.pending)
        }
        resolved = set(previous.pending) - set(current.pending)

        completed = []
        for pm in sorted(resolved, key=lambda pm: (pm.arrival_time, previous_order[pm])):
            origin_piece = current.board.get_piece_at(pm.from_pos)
            if origin_piece is not None and self._token_matches(origin_piece, pm.piece):
                continue  # never actually left -- dropped as invalid

            landed_piece = current.board.get_piece_at(pm.to_pos)
            if landed_piece is None or landed_piece.color.value != pm.piece[0]:
                continue  # never landed, or to_pos now holds something else entirely

            mover_kind = pm.piece[1]
            is_ordinary_landing = landed_piece.kind == mover_kind
            is_promotion = mover_kind == "P" and landed_piece.kind == "Q"
            if not (is_ordinary_landing or is_promotion):
                continue

            completed.append(
                CompletedMove(
                    time=pm.arrival_time,
                    color=landed_piece.color,
                    kind=landed_piece.kind,
                    destination=pm.to_pos,
                )
            )
        return completed

    @staticmethod
    def _token_matches(piece: PieceSnapshot, token: str) -> bool:
        return piece.color.value == token[0] and piece.kind == token[1]
