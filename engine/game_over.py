from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from core.models import Color, GameResult

if TYPE_CHECKING:
    from engine.board import AbstractBoard

# ---------------------------------------------------------------------------
# Kung Fu Chess – Game-Over Rules  (Strategy Pattern / OCP)
# ---------------------------------------------------------------------------
# Mirrors the MovementRule / MoveValidator split in ``engine.rules``:
#   GameOverRule (ABC)  – board-agnostic interface, one method: ``check``.
#     └── KingCaptureRule – the game ends the instant an armed King is gone.
#
# GameEngine is injected with a GameOverRule (constructor DI, defaults to
# KingCaptureRule) so future win conditions — checkmate, resignation,
# draw-by-repetition — plug in without touching GameEngine itself.
# ---------------------------------------------------------------------------


class GameOverRule(ABC):
    """Abstract Strategy for deciding whether the game has ended."""

    @abstractmethod
    def check(self, board: AbstractBoard) -> GameResult:
        """Inspect *board* and return the current ``GameResult``."""


class KingCaptureRule(GameOverRule):
    """The game ends the moment an armed side's King is captured.

    "Armed" is the key idea: this rule is stateful, and its *first*
    ``check()`` call establishes which colours actually started the game
    with a King on the board. Only an armed colour can subsequently
    "lose" by having its King disappear. A colour that never had a King
    to begin with — common in isolated single-piece test boards that
    exercise unrelated movement logic — can never end the game, because
    it was never armed in the first place.

    ``GameEngine`` primes each rule once at construction time, using the
    pristine starting board, before any move can execute — so priming
    always reflects the true initial position.

    A King is "captured" simply by no longer appearing anywhere on the
    board — this engine never soft-deletes pieces, so absence is exact.
    If both armed Kings are gone at once (e.g. a same-tick double
    capture) the result is a draw (``winner=None``).

    One instance is scoped to one game; don't share a ``KingCaptureRule``
    across two ``GameEngine`` instances.
    """

    def __init__(self) -> None:
        self._white_armed: bool | None = None
        self._black_armed: bool | None = None

    def check(self, board: AbstractBoard) -> GameResult:
        white_alive = self._king_present(board, Color.WHITE)
        black_alive = self._king_present(board, Color.BLACK)

        if self._white_armed is None:
            self._white_armed = white_alive
            self._black_armed = black_alive

        white_lost = self._white_armed and not white_alive
        black_lost = self._black_armed and not black_alive

        if not white_lost and not black_lost:
            return GameResult(is_over=False)
        if white_lost and black_lost:
            return GameResult(is_over=True, winner=None)
        return GameResult(
            is_over=True, winner=Color.BLACK if white_lost else Color.WHITE
        )

    @staticmethod
    def _king_present(board: AbstractBoard, color: Color) -> bool:
        token = f"{color.value}K"
        return any(token in row.split() for row in board.get_rows())
