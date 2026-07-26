from typing import Dict, FrozenSet

# ---------------------------------------------------------------------------
# Kung Fu Chess – Configuration
# ---------------------------------------------------------------------------
# Moved here from core.config (Iteration: shared/ extraction) — same
# values, same names, for the constants that already existed
# (VALID_PIECE_CHARS, PIECE_POINTS, CELL_SIZE, MOVE_DURATION,
# JUMP_DURATION, COOLDOWN_DURATION). BOARD_ROWS/BOARD_COLS and
# DEFAULT_HOST/DEFAULT_PORT are new additions — see each one's own
# comment below for exactly what it does and doesn't affect.
#
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

# Standard board dimensions. NOTE: this is a REFERENCE/DEFAULT value,
# not an enforced constraint -- shared.models.board.AbstractBoard/
# TextBoard are deliberately board-size-agnostic (this project's own
# test suite constructs boards as small as 1x1/2x2/3x3 throughout, for
# isolated single-rule tests), and nothing in the engine reads these two
# constants to decide how big a real board must be. They exist so
# callers that specifically want "the standard 8x8 dimensions" (e.g.
# server.algebraic's algebraic-notation conversion, which only makes
# sense for a standard board) have one named place to get that number
# from, instead of a bare literal "8".
BOARD_ROWS: int = 8
BOARD_COLS: int = 8

# Pixel dimensions of a single board cell.
CELL_SIZE: int = 100

# Duration (ms) per cell travelled for a pending move (Chebyshev distance).
MOVE_DURATION: int = 200

# Duration (ms) a jump keeps its piece airborne, defending its own cell.
JUMP_DURATION: int = 1000

# Duration (ms) a piece is unselectable after landing from a move or jump.
#
# NOTE: this is a single, piece-type-agnostic value -- GameEngine
# doesn't currently vary cooldown by piece type (_set_cooldown always
# uses this one constant, regardless of which piece just landed). A
# genuine "different cooldown per piece type" feature would need
# GameEngine._set_cooldown itself to branch on piece type, which is a
# real engine-behaviour change, not something a constants file alone
# can add -- so rather than ship a per-piece-type dict here that looks
# like it configures something it doesn't, this stays the single value
# that's actually wired up today.
COOLDOWN_DURATION: int = 1000

# Default WebSocket server bind address/port (server/server.py).
DEFAULT_HOST: str = "localhost"
DEFAULT_PORT: int = 8765
