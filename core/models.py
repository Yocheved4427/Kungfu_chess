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
