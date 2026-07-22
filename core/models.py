from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple

# ---------------------------------------------------------------------------
# Kung Fu Chess – Core domain models
# ---------------------------------------------------------------------------
# Pure value objects: no business logic, no I/O, no side-effects.
# All types are frozen so they are safely hashable and immutable.
# ---------------------------------------------------------------------------


class Color(Enum):
    """Piece colour encoded as the leading character of a board token."""
    WHITE = "w"
    BLACK = "b"


def same_color(piece_a: str | None, piece_b: str | None) -> bool:
    """Return True iff *piece_a* and *piece_b* are both real piece tokens
    (e.g. ``"wR"``, ``"bK"``) belonging to the same colour.

    False whenever either side is ``None`` — the shared home for a check
    that used to be duplicated (friendly-fire detection, selection/
    reselection, route-lock colour comparison) across engine.rules,
    engine.rule_engine, engine.game, and controllers.click_controller.
    """
    if piece_a is None or piece_b is None:
        return False
    return piece_a[0] == piece_b[0]


@dataclass(frozen=True)
class Position:
    """An (row, col) cell address on the board.  Immutable value object."""
    row: int
    col: int


@dataclass(frozen=True)
class MoveRequest:
    """Value object representing a requested piece move.

    Issued by the engine when a selection is committed.  Carries no state
    and triggers no side-effects.
    """
    from_pos: Position
    to_pos: Position


@dataclass(frozen=True)
class MoveCheckpoint:
    """One waypoint along a ``PendingMove``'s straight-line path — an
    intermediate cell, or the final destination — with its own due time.

    Lets ``GameEngine.tick()`` detect a friendly mid-route block at the
    specific moment it actually happens (see ``PendingMove.checkpoints``),
    rather than only at the move's single overall ``arrival_time``; the
    same per-cell timing also lets the UI interpolate a piece's on-screen
    position smoothly instead of teleporting it at the very end.
    """
    pos: Position
    due_time: int


@dataclass(frozen=True)
class PendingMove:
    """A validated move that is queued and waiting to arrive.

    ``piece``        – token at the origin cell at the moment the move was queued
                       (e.g. ``"wR"``).  Stored so the engine can double-check
                       the piece is still there when the move resolves.
    ``from_pos``     – origin cell.
    ``to_pos``       – destination cell.
    ``arrival_time`` – game-clock value (ms) at which the move executes.
    ``start_time``   – game-clock value (ms) at which the move was queued
                       — i.e. when it started travelling from ``from_pos``.
                       Together with ``checkpoints`` this fully describes
                       the move's timeline; unused (left at its default)
                       for a ``PendingMove`` built without checkpoint data.
    ``checkpoints``  – the FULL, unchanging ordered list of waypoints
                       (every intermediate cell, plus ``to_pos`` last) —
                       see ``MoveCheckpoint``. Built once when the move is
                       queued (``GameEngine.attempt_move``) and never
                       replaced; empty only for a ``PendingMove`` built
                       directly (e.g. in a test) without going through
                       that path, in which case ``GameEngine`` falls back
                       to treating the whole move as one single checkpoint
                       due at ``arrival_time`` — the same behaviour this
                       engine had before per-cell checkpoint timing
                       existed.
    ``next_checkpoint`` – index into ``checkpoints`` of the next one
                       ``GameEngine.tick()`` still needs to resolve;
                       advances by one each time a checkpoint is
                       confirmed clear of a friendly blocker (see
                       ``GameEngine._resolve_checkpoint``). Excluded from
                       equality/hashing (``compare=False``) — it's pure
                       bookkeeping for an otherwise-unfinished move, not
                       part of what makes two ``PendingMove``s "the same
                       move"; ``MoveHistoryTracker``/``ScoreTracker`` diff
                       consecutive snapshots' ``pending`` lists via set
                       difference to detect genuine completion, and must
                       keep seeing an in-flight move as unchanged while
                       only its checkpoint cursor advances.
    """
    piece: str
    from_pos: Position
    to_pos: Position
    arrival_time: int
    start_time: int = 0
    checkpoints: Tuple[MoveCheckpoint, ...] = ()
    next_checkpoint: int = field(default=0, compare=False)


@dataclass(frozen=True)
class PendingJump:
    """A piece committed to an in-place jump, defending its own cell.

    Unlike ``PendingMove``, a jump never relocates its piece — ``pos`` is
    both origin and destination for the jump's whole duration.

    ``piece``     – token at the cell when the jump started.
    ``pos``       – the cell the piece jumps from and returns to.
    ``land_time`` – game-clock value (ms) at which the piece grounds again,
                    provided no enemy arrived at ``pos`` during the jump.
    """
    piece: str
    pos: Position
    land_time: int


@dataclass(frozen=True)
class GameResult:
    """Outcome of a ``GameOverRule`` check against the current board.

    ``is_over``  – True once the game has ended.
    ``winner``   – the winning ``Color``, or ``None`` for a draw / ongoing
                   game (``winner`` is only meaningful when ``is_over``).
    """
    is_over: bool
    winner: Color | None = None
