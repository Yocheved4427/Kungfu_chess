from typing import Dict, FrozenSet

# ---------------------------------------------------------------------------
# Kung Fu Chess – Configuration
# ---------------------------------------------------------------------------
# All "magic values" live here so no other module hard-codes them.
#
# Piece encoding convention (standard chess notation):
#   "w" prefix → White piece  (wK wQ wR wB wN wP)
#   "b" prefix → Black piece  (bK bQ bR bB bN bP)
#   "."        → Empty square
# ---------------------------------------------------------------------------

VALID_PIECE_CHARS: FrozenSet[str] = frozenset([
    "wK", "wQ", "wR", "wB", "wN", "wP",
    "bK", "bQ", "bR", "bB", "bN", "bP",
    ".",
])

# Standard chess point values, keyed by piece-type char (the second
# character of a token, e.g. "wR" -> "R") -- the same "piece-type char"
# RuleEngine dispatches on (see engine.rule_engine's module docstring) and
# PieceSnapshot.kind already stores (see engine.snapshot). Colour-agnostic:
# a captured Rook is worth 5 points regardless of which side it belonged
# to, so this isn't duplicated per colour.
PIECE_POINTS: Dict[str, int] = {
    "P": 1,
    "N": 3,
    "B": 3,
    "R": 5,
    "Q": 9,
    "K": 0,
}

# Pixel dimensions of a single board cell.
CELL_SIZE: int = 100

# Duration (ms) per cell travelled for a pending move (Chebyshev distance).
MOVE_DURATION: int = 1000

# Duration (ms) a jump keeps its piece airborne, defending its own cell.
JUMP_DURATION: int = 1000

# Duration (ms) a piece is unselectable after landing from a move or jump.
COOLDOWN_DURATION: int = 1000
