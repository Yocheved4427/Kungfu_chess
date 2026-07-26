from __future__ import annotations

from shared.models.board import AbstractBoard
from shared.models.cell import Cell
from engine.geometry import path_clear

# ---------------------------------------------------------------------------
# Kung Fu Chess – Server Board Rules (facade)
# ---------------------------------------------------------------------------
# Thin facade over engine.geometry / shared.models.board.AbstractBoard:
# the actual boundary check (AbstractBoard.contains) and path-
# obstruction check (engine.geometry.path_clear) already exist, and are
# already the single implementation shared between both of engine/'s
# movement-rule systems (see engine/geometry.py's own docstring). This
# module just re-exposes them under server/game/rules' naming — no
# second bounds/collision implementation.
# ---------------------------------------------------------------------------


def is_within_bounds(cell: Cell, board: AbstractBoard) -> bool:
    """True iff *cell* is a real cell on *board*."""
    return board.contains(cell)


def is_path_clear(board: AbstractBoard, from_cell: Cell, to_cell: Cell) -> bool:
    """True iff every square strictly between *from_cell* and *to_cell*
    is empty. Assumes a straight line (orthogonal or diagonal) — same
    precondition as ``engine.geometry.path_clear``, which this wraps.
    """
    return path_clear(board, from_cell, to_cell)
