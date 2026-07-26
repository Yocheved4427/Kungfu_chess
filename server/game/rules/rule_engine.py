from __future__ import annotations

from enum import Enum, auto
from typing import Dict, List, Optional

from shared.models.board import AbstractBoard
from shared.models.cell import Cell
from engine.cooldown import is_resting
from engine.rule_engine import MoveResult
from engine.rule_engine import RuleEngine as _EnginePieceBoardRuleEngine
from server.game.rules.piece_rules import calculate_trajectories

# ---------------------------------------------------------------------------
# Kung Fu Chess – Server Rule Engine (facade)
# ---------------------------------------------------------------------------
# The one thing engine.rule_engine.RuleEngine itself has no notion of
# is TIME — it only ever reads board content to decide legality (see
# its own module docstring), never a clock. Real-time concerns
# (whether the piece at from_cell is still cooling down from its last
# landing) live instead in engine.game.GameEngine/GameState
# (``GameState.cooldowns``, ``GameEngine.is_in_cooldown``).
#
# This class unifies both: piece/board legality is fully delegated to
# engine.rule_engine.RuleEngine (itself already covering piece-type
# movement shape, friendly-fire, path-blocking, and board bounds — see
# piece_rules.py/board_rules.py, thin facades over the exact same
# engine logic) — nothing here re-derives any of that. The only new
# behaviour this module adds is the millisecond/cooldown check, using
# a plain ``{Cell: expiry_time_ms}`` mapping shaped exactly like
# ``GameState.cooldowns`` (see engine/game_state.py), so a caller that
# already has a ``GameState`` can pass ``state.cooldowns`` straight
# through without any adapting.
# ---------------------------------------------------------------------------


class MoveLegality(Enum):
    """Outcome of ``RuleEngine.validate_move`` below — a superset of
    ``engine.rule_engine.MoveResult`` that adds the real-time-only
    rejection reasons ``engine.rule_engine.RuleEngine`` has no way to
    know about (it only ever reads current board content — see its own
    module docstring):

    * ``PIECE_COOLING_DOWN`` — the mover hasn't finished cooling down
      from its last landing yet.
    * ``ROUTE_CONFLICT`` — this move's lane overlaps an opposite-colour
      piece already in transit along the same lane (see
      ``GameEngine.attempt_move``'s own route-lock check,
      ``_route_conflicts``) — never produced by this class's own
      ``validate_move``, only by ``real_time_arbiter.RealTimeArbiter``,
      which is the caller actually in a position to know about other
      pieces currently in flight.
    * ``GAME_OVER`` — mirrors ``engine.rule_engine.MoveResult.GAME_OVER``
      (also never produced by this class's own ``validate_move``, for
      the same reason: it reads board content, not ``GameState.
      game_over`` — only a caller holding the full ``GameState``, i.e.
      ``RealTimeArbiter``, can know a game has already ended).

    Every other member corresponds 1:1 (same name) to an
    ``engine.rule_engine.MoveResult`` member — see ``_from_move_result``.
    """
    OK = auto()
    OUTSIDE_BOARD = auto()
    SAME_POSITION = auto()
    EMPTY_SOURCE = auto()
    UNKNOWN_PIECE_TYPE = auto()
    ILLEGAL_PATTERN = auto()
    FRIENDLY_FIRE = auto()
    BLOCKED_PATH = auto()
    PIECE_COOLING_DOWN = auto()
    ROUTE_CONFLICT = auto()
    GAME_OVER = auto()

    @property
    def is_ok(self) -> bool:
        return self is MoveLegality.OK


def _from_move_result(result: MoveResult) -> MoveLegality:
    """Translate an ``engine.rule_engine.MoveResult`` into the matching
    ``MoveLegality`` member — every member name lines up except
    ``MoveResult.GAME_OVER``, which ``RuleEngine.validate_move`` never
    produces (see that method's own docstring) and so is never passed
    here."""
    return MoveLegality[result.name]


class RuleEngine:
    """Unifies piece/board legality with real-time cooldown awareness.

    Delegates every piece-type/board-geometry decision to
    ``engine.rule_engine.RuleEngine`` (constructor-injectable, same
    idea as that class's own ``register()`` extension point) — this
    class's only original logic is the cooldown check.
    """

    def __init__(
        self, piece_board_rules: Optional[_EnginePieceBoardRuleEngine] = None
    ) -> None:
        self._piece_board_rules: _EnginePieceBoardRuleEngine = (
            piece_board_rules
            if piece_board_rules is not None
            else _EnginePieceBoardRuleEngine()
        )

    def validate_move(
        self,
        piece: str,
        from_cell: Cell,
        to_cell: Cell,
        board: AbstractBoard,
        current_time_ms: int,
        cooldowns: Dict[Cell, int],
    ) -> MoveLegality:
        """Is moving *piece* from *from_cell* to *to_cell* legal, right
        now, at *current_time_ms*?

        Checks cooldown first (cheap, and a busy piece can't move
        regardless of shape) — then, only if that passes, delegates
        the rest to ``engine.rule_engine.RuleEngine.validate_move``.
        *cooldowns* is shaped exactly like ``GameState.cooldowns``:
        ``{Cell: expiry_time_ms}`` for cells still cooling down after a
        landing.
        """
        if self._is_cooling_down(from_cell, current_time_ms, cooldowns):
            return MoveLegality.PIECE_COOLING_DOWN
        result = self._piece_board_rules.validate_move(piece, from_cell, to_cell, board)
        return _from_move_result(result)

    def legal_destinations(
        self,
        piece: str,
        from_cell: Cell,
        board: AbstractBoard,
        current_time_ms: int,
        cooldowns: Dict[Cell, int],
    ) -> List[Cell]:
        """Every cell *piece* at *from_cell* could legally move to right
        now — empty (rather than raising/erroring) iff the piece
        itself is still cooling down. Built on ``piece_rules.
        calculate_trajectories`` (piece/board legality only); the
        cooldown check is this class's own addition, applied once to
        the whole set rather than per candidate cell.
        """
        if self._is_cooling_down(from_cell, current_time_ms, cooldowns):
            return []
        return calculate_trajectories(piece, from_cell, board)

    @staticmethod
    def _is_cooling_down(
        cell: Cell, current_time_ms: int, cooldowns: Dict[Cell, int]
    ) -> bool:
        return is_resting(cooldowns, cell, current_time_ms)
