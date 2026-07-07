from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


# ---------------------------------------------------------------------------
# Kung Fu Chess – Board representation
# ---------------------------------------------------------------------------
# AbstractBoard is the stable contract used by every other layer.
# Swap TextBoard for a bitboard, binary, or network representation at any
# time without touching the parser, validator, or I/O handler.
# ---------------------------------------------------------------------------


class AbstractBoard(ABC):
    """
    Language-agnostic interface for a chess board.

    All business logic depends on this interface, never on a concrete class,
    so the internal storage format can be replaced freely (Open/Closed).
    """

    @abstractmethod
    def get_rows(self) -> List[str]:
        """Return the board as an ordered list of row strings (top → bottom)."""

    @property
    @abstractmethod
    def num_rows(self) -> int:
        """Total number of ranks on the board."""

    @property
    @abstractmethod
    def num_cols(self) -> int:
        """Total number of files on the board."""

    @abstractmethod
    def render(self) -> str:
        """
        Produce the canonical text representation of the board.
        Rows are separated by newline characters; no trailing newline is added
        by this method (the caller controls line termination).
        """


class TextBoard(AbstractBoard):
    """
    Concrete board that stores each rank as a plain Python string.

    Each character in a string is one square.  This is the default
    representation for Iteration 1 (text I/O).
    """

    def __init__(self, rows: List[str]) -> None:
        # Defensive copy so the caller cannot mutate internal state.
        self._rows: List[str] = list(rows)

    # ------------------------------------------------------------------
    # AbstractBoard implementation
    # ------------------------------------------------------------------

    def get_rows(self) -> List[str]:
        return list(self._rows)          # return a copy for encapsulation

    @property
    def num_rows(self) -> int:
        return len(self._rows)

    @property
    def num_cols(self) -> int:
        return len(self._rows[0]) if self._rows else 0

    def render(self) -> str:
        return "\n".join(self._rows)
