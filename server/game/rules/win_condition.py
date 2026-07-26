from __future__ import annotations

from shared.models.board import AbstractBoard
from core.models import GameResult
from engine.game_over import GameOverRule, KingCaptureRule

# ---------------------------------------------------------------------------
# Kung Fu Chess – Server Win Condition (facade)
# ---------------------------------------------------------------------------
# Thin facade over engine.game_over. KingCaptureRule already is the
# real-time victory-condition evaluator engine.game.GameEngine is
# constructed with by default — checked after every completed move,
# not just at some end-of-game step (see GameEngine._capture_just_ended_
# the_game / tick()). This module re-exposes it (and its ABC) under
# server/game/rules instead of a second implementation.
# ---------------------------------------------------------------------------

__all__ = ["GameOverRule", "KingCaptureRule", "evaluate"]


def evaluate(rule: GameOverRule, board: AbstractBoard) -> GameResult:
    """Ask *rule* (typically a ``KingCaptureRule``) whether *board*'s
    current occupancy already ends the game."""
    return rule.check(board)
