from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Kung Fu Chess – Board Coordinate
# ---------------------------------------------------------------------------
# Moved here from core.models (as ``Position``) — renamed ``Cell`` to
# match this project's shared/ layer, but keeping the exact same
# ``(row, col)`` fields and semantics as before, NOT ``(x, y)``.
#
# Deliberately not (x, y): pixel-space (x, y) coordinates are a
# DIFFERENT, already-existing concept in this codebase —
# ``input.board_mapper.BoardMapper`` is the sole place that translates
# between a board Cell and a pixel (x, y) position (see that module's
# own docstring: "the one place pixel<->cell arithmetic happens").
# Reusing x/y for board coordinates too would blur a distinction this
# codebase has deliberately kept sharp everywhere else — use
# ``as_tuple()``/``from_tuple()`` below, or ``BoardMapper``, when an
# actual (x, y) pixel pair is what's needed instead of a board cell.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Cell:
    """A ``(row, col)`` cell address on the board. Immutable value object.

    ``order=True`` adds the full set of comparison operators (``<``,
    ``<=``, ``>``, ``>=``), compared lexicographically by
    ``(row, col)`` — e.g. useful for sorting a collection of cells into
    a stable, deterministic order. Equality/hashing (already present
    via ``frozen=True``) are unaffected by this.
    """
    row: int
    col: int

    def as_tuple(self) -> "tuple[int, int]":
        """Return ``(row, col)`` as a plain tuple."""
        return (self.row, self.col)

    @classmethod
    def from_tuple(cls, value: "tuple[int, int]") -> "Cell":
        """Build a ``Cell`` from a plain ``(row, col)`` tuple — the
        inverse of ``as_tuple()``."""
        row, col = value
        return cls(row=row, col=col)
