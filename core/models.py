from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

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
class PendingMove:
    """A validated move that is queued and waiting to arrive.

    ``piece``        – token at the origin cell at the moment the move was queued
                       (e.g. ``"wR"``).  Stored so the engine can double-check
                       the piece is still there when the move resolves.
    ``from_pos``     – origin cell.
    ``to_pos``       – destination cell.
    ``arrival_time`` – game-clock value (ms) at which the move executes.
    """
    piece: str
    from_pos: Position
    to_pos: Position
    arrival_time: int


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
