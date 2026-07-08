from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------------
# Kung Fu Chess – Domain models (Iteration 2)
# ---------------------------------------------------------------------------
# All models are frozen dataclasses or Enums so they are immutable value
# objects.  No business logic lives here; this module is a pure data layer.
# ---------------------------------------------------------------------------


class Color(Enum):
    """Piece colour encoded as the leading character of a board token."""
    WHITE = "w"
    BLACK = "b"


@dataclass(frozen=True)
class Position:
    """An (row, col) cell address on the board.  Immutable."""
    row: int
    col: int


@dataclass(frozen=True)
class MoveRequest:
    """
    A request to move the piece at *from_pos* to *to_pos*.

    Issued by GameEngine when a selection is committed.  Intentionally a
    plain value object: it carries no state and triggers no side-effects.
    """
    from_pos: Position
    to_pos: Position
