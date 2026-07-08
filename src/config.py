from typing import FrozenSet

# ---------------------------------------------------------------------------
# Kung Fu Chess – Configuration
# ---------------------------------------------------------------------------
# Centralise every "magic value" here so no other module hard-codes them.
#
# Piece encoding convention (standard chess notation):
#   Uppercase  → White piece  (K Q R B N P)
#   Lowercase  → Black piece  (k q r b n p)
#   '.'        → Empty square
# ---------------------------------------------------------------------------

VALID_PIECE_CHARS: FrozenSet[str] = frozenset([
    "wK", "wQ", "wR", "wB", "wN", "wP",
    "bK", "bQ", "bR", "bB", "bN", "bP",
    ".",
])

# Pixel dimensions of a single board cell.
CELL_SIZE: int = 100
