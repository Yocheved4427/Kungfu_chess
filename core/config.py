from typing import FrozenSet

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

# Pixel dimensions of a single board cell.
CELL_SIZE: int = 100

# Duration (ms) per cell travelled for a pending move (Chebyshev distance).
MOVE_DURATION: int = 1000

# Duration (ms) a jump keeps its piece airborne, defending its own cell.
JUMP_DURATION: int = 1000
