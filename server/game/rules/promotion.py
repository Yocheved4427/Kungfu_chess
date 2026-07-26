from __future__ import annotations

from shared.models.board import AbstractBoard
from shared.models.cell import Cell
from engine.promotion import is_promotion, promoted_piece, promotion_row

# ---------------------------------------------------------------------------
# Kung Fu Chess – Server Promotion Rules (facade)
# ---------------------------------------------------------------------------
# Thin facade over engine.promotion — the actual pawn-promotion
# decision logic (which row, which piece types, what a Pawn becomes).
# engine.game.GameEngine._maybe_promote calls those exact same
# functions to apply promotion as a board mutation once a move
# resolves; this module re-exposes them for server/game/rules callers
# instead of a second copy of the row/piece-type arithmetic.
# ---------------------------------------------------------------------------

__all__ = ["is_promotion", "promoted_piece", "promotion_row", "should_promote"]


def should_promote(piece: str, pos: Cell, board: AbstractBoard) -> bool:
    """True iff *piece* sitting at *pos* on *board* has just reached its
    colour's back rank and should promote. Always False for a
    non-Pawn.
    """
    return is_promotion(piece, pos, board.num_rows)
