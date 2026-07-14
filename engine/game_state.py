from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from core.models import Color, PendingJump, PendingMove, Position
from engine.board import AbstractBoard

# ---------------------------------------------------------------------------
# Kung Fu Chess – Game State
# ---------------------------------------------------------------------------
# Extracted out of GameEngine (SRP: state vs. logic). Every field here is
# mutated somewhere in GameEngine over the course of a game; nothing here
# is a service/collaborator (MoveValidator, RuleEngine, CollisionResolver,
# BoardMapper, ...) or static per-game config (move/jump/cooldown
# duration) — those stay as GameEngine's own attributes, since they don't
# change once the game is constructed and aren't part of "where the game
# currently stands".
#
# Bundling everything mutable behind one ``GameEngine.state`` attribute
# means a save/load or replay feature is a matter of (de)serializing this
# one dataclass, and a test can construct or swap in a whole fake game
# state without touching GameEngine's constructor signature.
#
# Deliberately a plain (non-frozen) dataclass, unlike core.models' value
# objects: this is mutable by design, and it depends on ``AbstractBoard``
# (an engine-layer type) — core.models stays free of any engine import,
# so it can't live there without inverting that dependency direction.
# ---------------------------------------------------------------------------


@dataclass
class GameState:
    """All of a game-in-progress's mutable state, held as a single unit.

    ``board``        – current board occupancy. GameEngine is still the
                        only thing that mutates it in place
                        (``move_piece``/``set_piece_at``); this class
                        just holds the reference.
    ``current_time`` – game clock, ms, monotonically advanced by
                        ``GameEngine.tick``.
    ``pending``      – queued moves not yet arrived (``PendingMove``).
    ``airborne``     – pieces currently mid-jump (``PendingJump``).
    ``cooldowns``    – ``{Position: expiry_time_ms}`` for cells still
                        cooling down after a landing (see
                        ``GameEngine.is_in_cooldown``).
    ``game_over``    – True once a ``GameOverRule`` has ended the game.
    ``winner``       – the winning ``Color``, or ``None`` for a draw or
                        a still-ongoing game.
    """

    board: AbstractBoard
    current_time: int = 0
    pending: List[PendingMove] = field(default_factory=list)
    airborne: List[PendingJump] = field(default_factory=list)
    cooldowns: Dict[Position, int] = field(default_factory=dict)
    game_over: bool = False
    winner: Color | None = None
