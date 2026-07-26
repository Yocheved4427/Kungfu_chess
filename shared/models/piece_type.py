from __future__ import annotations

from enum import Enum

# ---------------------------------------------------------------------------
# Kung Fu Chess – Piece Type
# ---------------------------------------------------------------------------
# NEW — there was no PieceType enum anywhere in this codebase before this
# file. Every existing component (engine.rule_engine's registry,
# engine.rules' MoveValidator, engine.snapshot.PieceSnapshot.kind, ...)
# dispatches on the raw piece-type CHARACTER instead — the second
# character of a two-char board token, e.g. "wR" -> "R" (see
# engine.rule_engine's own module docstring for that convention).
#
# This enum is NOT wired into that dispatch — introducing it there would
# mean reworking RuleEngine's registry and every call site that currently
# matches on a bare ``str``, which is a separate, considerably larger
# change than "add an enum". ``value`` below is exactly the character
# every existing component already keys on, so converting between the
# two is a one-liner (``PieceType(piece[1])`` / ``piece_type.value``)
# whenever something DOES want to use this enum instead of a raw char.
# ---------------------------------------------------------------------------


class PieceType(Enum):
    """Chess piece type, keyed by the same single-character code this
    project's board tokens already use as their second character
    (e.g. ``"wR"`` -> ``"R"``)."""
    PAWN = "P"
    KNIGHT = "N"
    BISHOP = "B"
    ROOK = "R"
    QUEEN = "Q"
    KING = "K"
