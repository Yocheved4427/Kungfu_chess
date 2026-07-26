from __future__ import annotations

from shared.models.cell import Cell

# ---------------------------------------------------------------------------
# Kung Fu Chess – Pawn Promotion
# ---------------------------------------------------------------------------
# Pure decision logic, extracted out of GameEngine._maybe_promote so it
# has exactly one home. GameEngine still owns the actual board mutation
# (promotion is a board mutation applied after a move resolves, not a
# legality concern — see engine.rules.PawnRule's own docstring); it
# just calls through to the functions here instead of repeating the
# row/piece-type arithmetic inline. This also lets server/game/rules
# (a facade layer over engine/) re-expose the same, single
# implementation instead of a second copy.
# ---------------------------------------------------------------------------


def promotion_row(piece: str, num_rows: int) -> int:
    """The back rank *piece*'s colour promotes on: row 0 for White (the
    row it advances toward), ``num_rows - 1`` for Black — the mirror
    image, matching the direction convention in
    ``engine.geometry.pawn_direction``."""
    return 0 if piece[0] == "w" else num_rows - 1


def is_promotion(piece: str, pos: Cell, num_rows: int) -> bool:
    """True iff *piece* sitting at *pos* has just reached its colour's
    back rank and should promote. Always False for a non-Pawn."""
    return piece[1] == "P" and pos.row == promotion_row(piece, num_rows)


def promoted_piece(piece: str) -> str:
    """The token *piece* (a Pawn) becomes on promotion — its own
    colour's Queen. Only meaningful when ``is_promotion`` is True for
    the same piece/position."""
    return piece[0] + "Q"
