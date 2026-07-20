from __future__ import annotations

from core.models import Position

# ---------------------------------------------------------------------------
# Kung Fu Chess – Algebraic Notation
# ---------------------------------------------------------------------------
# Converts between standard chess square names ("e2") and this engine's
# (row, col) Position — the wire format server.server's move protocol
# uses for a client's "from"/"to" fields. No such conversion existed
# anywhere in the codebase before this (checked input/board_parser.py,
# input/board_mapper.py, core/models.py — all pixel/row-text, never
# algebraic).
#
# Hardcoded to the standard 8x8 board (files a-h, ranks 1-8) —
# algebraic notation is inherently an 8x8 concept. This engine's
# ability to run on other board sizes (used throughout tests/unit) has
# no bearing here: the server only ever plays the standard starting
# position (see ui/game_factory.py's STANDARD_BOARD_ROWS).
#
# Rank 1 is White's back rank, conventionally drawn at the BOTTOM of a
# board — this engine's row 0 is the TOP (Black's back rank; see
# STANDARD_BOARD_ROWS' own layout), so rank and row count in opposite
# directions: row = 8 - rank.
# ---------------------------------------------------------------------------

_FILES = "abcdefgh"
_NUM_RANKS = 8


class AlgebraicNotationError(ValueError):
    """Raised when a string isn't a valid algebraic square name."""


def algebraic_to_position(square: str) -> Position:
    """Parse a square name like ``"e2"`` into a ``Position``.

    Raises ``AlgebraicNotationError`` iff *square* isn't exactly a
    lowercase-or-uppercase file letter (a-h) followed by a rank digit
    (1-8) — never raises any other exception type, so a caller only
    needs to catch this one.
    """
    if not isinstance(square, str) or len(square) != 2:
        raise AlgebraicNotationError(f"Invalid square {square!r}: must be 2 characters")

    file_char, rank_char = square[0].lower(), square[1]
    if file_char not in _FILES:
        raise AlgebraicNotationError(f"Invalid square {square!r}: unknown file {square[0]!r}")
    if not rank_char.isdigit():
        raise AlgebraicNotationError(f"Invalid square {square!r}: unknown rank {rank_char!r}")

    rank = int(rank_char)
    if not (1 <= rank <= _NUM_RANKS):
        raise AlgebraicNotationError(
            f"Invalid square {square!r}: rank must be 1-{_NUM_RANKS}"
        )

    return Position(row=_NUM_RANKS - rank, col=_FILES.index(file_char))


def position_to_algebraic(position: Position) -> str:
    """Format a ``Position`` as a square name like ``"e2"`` — the
    inverse of ``algebraic_to_position``.

    Raises ``AlgebraicNotationError`` iff *position* falls outside the
    standard 8x8 board.
    """
    if not (0 <= position.row < _NUM_RANKS and 0 <= position.col < len(_FILES)):
        raise AlgebraicNotationError(
            f"{position!r} is outside the standard 8x8 board"
        )
    return f"{_FILES[position.col]}{_NUM_RANKS - position.row}"
