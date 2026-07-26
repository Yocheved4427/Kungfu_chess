from __future__ import annotations

from typing import List

from shared.models.board import AbstractBoard
from shared.models.cell import Cell
from engine.rule_engine import RuleEngine

# ---------------------------------------------------------------------------
# Kung Fu Chess – Server Piece Rules (facade)
# ---------------------------------------------------------------------------
# Thin facade, not a second rule implementation. Its job is to
# CALCULATE the set of destination cells a piece could legally reach
# right now, by asking engine.rule_engine.RuleEngine — the same
# registry-based, per-piece-type validator (RookRule / BishopRule /
# QueenRule / KnightRule / KingRule / PawnRule) that
# engine.game.GameEngine.try_move already uses — one from/to legality
# check per candidate cell on the board. Piece-type dispatch,
# friendly-fire, path-blocking, and board bounds are all still handled
# by that single, existing implementation; nothing here re-derives a
# piece type's movement shape from scratch.
#
# See board_rules.py for the bounds/obstruction checks in isolation,
# and rule_engine.py for the facade that adds real-time
# (millisecond/cooldown) awareness on top of a single from -> to
# legality check.
# ---------------------------------------------------------------------------

_rule_engine = RuleEngine()  # stateless registry (see RuleEngine's own
                             # docstring) — one shared instance is safe


def calculate_trajectories(
    piece: str, from_cell: Cell, board: AbstractBoard
) -> List[Cell]:
    """Every cell *piece* (e.g. ``"wN"``) at *from_cell* could legally
    move to right now, given *board*'s current occupancy.

    Covers all six piece types (Pawn, Knight, Bishop, Rook, Queen,
    King) via ``RuleEngine``'s own piece-type registry — one function
    here rather than six, matching that registry's OCP extension point
    (``RuleEngine.register``): a new piece type needs no change here.
    """
    destinations: List[Cell] = []
    for row in range(board.num_rows):
        for col in range(board.num_cols):
            to_cell = Cell(row=row, col=col)
            if _rule_engine.validate_move(piece, from_cell, to_cell, board).is_ok:
                destinations.append(to_cell)
    return destinations
