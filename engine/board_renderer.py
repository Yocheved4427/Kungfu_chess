from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.board import AbstractBoard

# ---------------------------------------------------------------------------
# Kung Fu Chess – Board Rendering  (Strategy Pattern / OCP)
# ---------------------------------------------------------------------------
# Turning board state into a displayable form is a presentation concern,
# not something AbstractBoard/TextBoard should know about — Board only
# knows logical (row, col) positions and piece tokens.
#
# GameEngine is injected with a BoardRenderer (constructor DI, defaults to
# TextBoardRenderer) so alternative presentations — JSON, a GUI-facing
# grid, ANSI colour, whatever — plug in without touching Board or
# GameEngine itself.
# ---------------------------------------------------------------------------


class BoardRenderer(ABC):
    """Abstract Strategy for turning board state into a displayable form."""

    @abstractmethod
    def render(self, board: AbstractBoard) -> str:
        """Return a rendering of *board*."""


class TextBoardRenderer(BoardRenderer):
    """Canonical text representation: rows joined by newlines.

    This is the exact "Board:" text format the VPL pipeline reads and
    ``print board`` writes back out — no trailing newline.
    """

    def render(self, board: AbstractBoard) -> str:
        return "\n".join(board.get_rows())
