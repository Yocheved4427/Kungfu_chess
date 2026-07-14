from __future__ import annotations

from typing import TYPE_CHECKING

from core.models import Position

if TYPE_CHECKING:
    from engine.board import AbstractBoard

# ---------------------------------------------------------------------------
# Kung Fu Chess – Shared movement geometry
# ---------------------------------------------------------------------------
# Pure, board-math helpers used by BOTH movement-rule systems in this
# codebase: engine.rules (MovementRule / MoveValidator, backing
# GameEngine.attempt_move — the real-time, queued pipeline) and
# engine.rule_engine (IPieceRule / RuleEngine, backing GameEngine.try_move
# — the synchronous, MoveResult-returning pipeline).
#
# The two systems intentionally keep different public interfaces and
# control flow (one returns bool, the other a MoveResult enum; one is
# organized by movement SHAPE, the other by piece TYPE) — but the
# underlying chess math (is this move a straight line? a diagonal? an
# L-shape? one step? is the path between two cells clear?) is exactly
# the same, and used to be duplicated between them. This module is that
# single shared implementation.
# ---------------------------------------------------------------------------


def is_orthogonal(from_pos: Position, to_pos: Position) -> bool:
    """True iff the move is purely horizontal or purely vertical."""
    dr = to_pos.row - from_pos.row
    dc = to_pos.col - from_pos.col
    return (dr == 0) != (dc == 0)   # exactly one axis moves


def is_diagonal(from_pos: Position, to_pos: Position) -> bool:
    """True iff the move is a non-zero-length diagonal."""
    dr = abs(to_pos.row - from_pos.row)
    dc = abs(to_pos.col - from_pos.col)
    return dr == dc and dr > 0


def is_knight_shape(from_pos: Position, to_pos: Position) -> bool:
    """True iff the move is a Knight's L-shape (2-and-1 in either order)."""
    dr = abs(to_pos.row - from_pos.row)
    dc = abs(to_pos.col - from_pos.col)
    return (dr, dc) in {(1, 2), (2, 1)}


def is_king_step(from_pos: Position, to_pos: Position) -> bool:
    """True iff the move is exactly one step, in any of the 8 directions."""
    dr = abs(to_pos.row - from_pos.row)
    dc = abs(to_pos.col - from_pos.col)
    if max(dr, dc) != 1:
        return False
    return is_orthogonal(from_pos, to_pos) or is_diagonal(from_pos, to_pos)


def pawn_direction(piece: str) -> int:
    """The row-delta a Pawn's single forward step moves in.

    White (``piece[0] == 'w'``) advances toward decreasing row (-1);
    Black advances toward increasing row (+1).
    """
    return -1 if piece[0] == "w" else 1


def pawn_start_row(piece: str, num_rows: int) -> int:
    """The board row a Pawn's colour starts on — one row in front of the
    back rank it advances *away* from: ``num_rows - 2`` for White, row 1
    for Black. Only relevant to the two-step advance."""
    return num_rows - 2 if piece[0] == "w" else 1


def path_clear(board: AbstractBoard, from_pos: Position, to_pos: Position) -> bool:
    """Return True iff every square strictly between *from_pos* and
    *to_pos* is empty. Assumes a straight line (orthogonal or diagonal);
    behaviour is undefined otherwise."""
    dr = to_pos.row - from_pos.row
    dc = to_pos.col - from_pos.col
    steps = max(abs(dr), abs(dc))
    step_r = dr // steps
    step_c = dc // steps
    r, c = from_pos.row + step_r, from_pos.col + step_c
    while (r, c) != (to_pos.row, to_pos.col):
        if board.get_piece_at(Position(r, c)) != ".":
            return False
        r += step_r
        c += step_c
    return True
