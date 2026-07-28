"""Piece type/colour + a read-only Piece value object.

``PieceType``/``Color`` are thin re-exports of ``shared/models/piece_type.py``
and ``shared/models/color.py`` (repo root, also used by the server). The
``Piece`` dataclass below is genuinely NEW -- there was no standalone
"one piece" value object anywhere in this codebase before this; pieces
are represented as plain two-character board tokens (e.g. ``"wK"``)
everywhere else. This is an additive convenience read-model built FROM
a board+cell, not a second source of truth: it never mutates a board,
and it deliberately carries no "state" (idle/moving/jumping/resting)
field of its own -- see ``src.core.state_machine.PieceLifecycleState``
for that, since state is a live, per-tick property of a ``GameState``,
not something a static Piece snapshot can own without going stale.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.models.cell import Cell
from shared.models.color import Color
from shared.models.piece_type import PieceType

__all__ = ["Color", "PieceType", "Piece"]


@dataclass(frozen=True)
class Piece:
    """One piece's identity + location, read from a board at a point in time."""

    piece_type: PieceType
    color: Color
    position: Cell

    @classmethod
    def at(cls, board, position: Cell) -> "Piece | None":
        """Build a ``Piece`` from whatever occupies *position* on
        *board* (any ``shared.models.board.AbstractBoard``), or
        ``None`` if that cell is empty/off-board.
        """
        token = board.get_piece_at(position)
        if token is None or token == ".":
            return None
        return cls(
            piece_type=PieceType(token[1]),
            color=Color(token[0]),
            position=position,
        )
