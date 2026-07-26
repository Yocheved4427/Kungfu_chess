from __future__ import annotations

from typing import Optional

from shared.models.cell import Cell
from engine.game import GameEngine
from engine.game_state import GameState
from ui.events import Observer
from server.game.rules.rule_engine import MoveLegality
from server.game.rules.rule_engine import RuleEngine as _RulesFacade

# ---------------------------------------------------------------------------
# Kung Fu Chess – Real-Time Arbiter (facade / orchestrator)
# ---------------------------------------------------------------------------
# Core real-time game-loop orchestrator: receives a move request,
# verifies legality (piece/board rules + cooldown, via
# server.game.rules.rule_engine.RuleEngine) before it ever reaches the
# engine, applies it via GameEngine.attempt_move — the same queued,
# checkpoint-timed pipeline this codebase's real-time play already
# runs on (see engine/game.py's own module docstring) — advances the
# clock, and broadcasts every resulting GameEvent to observers.
#
# This wraps GameEngine/GameState rather than reimplementing any part
# of their pipeline. server/server.py's GameServer already drives this
# exact engine for its websocket-connected players (see
# GameServer._handle_move / _tick_loop / _BroadcastObserver) — this
# class packages that same receive -> validate -> apply -> broadcast
# orchestration as a standalone, transport-agnostic component (no
# websocket/JSON/login concerns of its own, unlike GameServer). It is
# NOT currently wired into GameServer — that would be a follow-up
# integration (e.g. GameServer delegating its own _handle_move/
# _tick_loop bodies to an owned RealTimeArbiter instance), not a
# rewrite of anything working today.
# ---------------------------------------------------------------------------


class RealTimeArbiter:
    """Owns one game's engine + state and arbitrates real-time play
    against it: one move request at a time, plus clock advancement.
    """

    def __init__(
        self,
        engine: GameEngine,
        state: GameState,
        rule_engine: Optional[_RulesFacade] = None,
    ) -> None:
        self._engine = engine
        self._state = state
        self._rule_engine: _RulesFacade = (
            rule_engine if rule_engine is not None else _RulesFacade()
        )

    @property
    def state(self) -> GameState:
        """The live ``GameState`` this arbiter's engine mutates —
        exposed read-only so a caller (e.g. a broadcast loop building a
        snapshot message) can read ``board``/``current_time``/
        ``game_over``/``winner`` directly, the same convention
        ``GameEngine`` itself uses (see that class's own note on why
        it has no shim properties over ``GameState``).
        """
        return self._state

    def add_observer(self, observer: Observer) -> None:
        """Register *observer* to receive every ``GameEvent`` this
        arbiter's moves/ticks produce — forwards straight to
        ``GameEngine.add_observer``; this class has no event bus of
        its own. To actually broadcast to connected players, register
        an ``Observer`` that pushes each event onward (the same shape
        as ``server.server._BroadcastObserver``).
        """
        self._engine.add_observer(observer)

    def submit_move(self, from_cell: Cell, to_cell: Cell) -> MoveLegality:
        """Handle one player's move request from *from_cell* to
        *to_cell*, returning precisely why it was accepted or rejected.

        Checked in order:

        1. The game isn't already over (``GameState.game_over``) — the
           one thing neither ``RuleEngine`` below nor ``GameEngine.
           attempt_move`` reports distinctly on its own (``attempt_move``
           just returns False for this same reason, among others).
        2. ``RuleEngine.validate_move`` — piece/board shape, friendly-
           fire, path-blocking, board bounds, and cooldown. Rejected
           here without ever touching ``GameEngine``.
        3. ``GameEngine.attempt_move`` itself, only once (1) and (2)
           passed — this applies the one further real-time-only check
           ``RuleEngine`` cannot see (``_route_conflicts``: an
           opposite-colour piece already in transit along the same
           lane). A rejection at this layer is reported as
           ``MoveLegality.ROUTE_CONFLICT`` — the only reason
           ``attempt_move`` can still say no once (1) and (2) have
           already passed.

        ``MoveLegality.OK`` means the move was accepted and QUEUED —
        same as every other real-time move in this codebase: the piece
        relocates later, when ``advance()`` reaches its arrival time,
        firing a ``MoveCompletedEvent`` to every registered observer at
        that point. Nothing here applies a move immediately.
        """
        if self._state.game_over:
            return MoveLegality.GAME_OVER

        piece = self._state.board.get_piece_at(from_cell) or "."
        legality = self._rule_engine.validate_move(
            piece,
            from_cell,
            to_cell,
            self._state.board,
            self._state.current_time,
            self._state.cooldowns,
        )
        if not legality.is_ok:
            return legality

        if not self._engine.attempt_move(self._state, from_cell, to_cell):
            return MoveLegality.ROUTE_CONFLICT

        return MoveLegality.OK

    def advance(self, ms: int) -> None:
        """Advance the game clock by *ms* and resolve every checkpoint
        now due — forwards straight to ``GameEngine.tick``, which fires
        ``MoveCompletedEvent``/``JumpLandedEvent``/``GameOverEvent``/
        ``TimeAdvancedEvent`` to every observer registered via
        ``add_observer`` as they occur. "Broadcasts state updates to
        all connected players" is exactly this: an observer that
        forwards each event to connected clients, driven by regular
        calls to this method (a tick loop) — see this module's own
        docstring.
        """
        self._engine.tick(self._state, ms)
