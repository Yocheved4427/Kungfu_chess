"""
Unit tests for ``GameState`` (Kungfu Chess).

Covers the dataclass itself (defaults, independence between instances)
and that ``GameEngine`` wires a single ``GameState`` instance up as
``self.state`` and keeps its read-only compatibility aliases
(``board``/``game_over``/``winner``/``_pending``/``_airborne``) in sync
with it. The state machine's *behavior* (moves, jumps, cooldowns, game
over) is already covered end-to-end elsewhere (test_engine.py,
test_jump.py, test_cooldown.py, ...) — this file only checks the shape
of the state container and the engine's wiring to it.
"""

from __future__ import annotations

from core.models import PendingJump, PendingMove, Position
from engine.board import TextBoard
from engine.game import GameEngine
from engine.game_state import GameState


class TestGameStateDefaults:
    def test_defaults_on_construction(self):
        board = TextBoard(["wK ."])
        state = GameState(board=board)
        assert state.board is board
        assert state.current_time == 0
        assert state.pending == []
        assert state.airborne == []
        assert state.cooldowns == {}
        assert state.game_over is False
        assert state.winner is None

    def test_default_collections_are_not_shared_between_instances(self):
        """A dataclass with a bare mutable default would leak state across
        instances — this checks GameState uses field(default_factory=...)
        rather than a shared literal."""
        state_a = GameState(board=TextBoard(["wK ."]))
        state_b = GameState(board=TextBoard(["wK ."]))
        state_a.pending.append(
            PendingMove(piece="wK", from_pos=Position(0, 0), to_pos=Position(0, 1), arrival_time=100)
        )
        state_a.airborne.append(PendingJump(piece="wK", pos=Position(0, 0), land_time=100))
        state_a.cooldowns[Position(0, 0)] = 100
        assert state_b.pending == []
        assert state_b.airborne == []
        assert state_b.cooldowns == {}


class TestGameEngineStateWiring:
    def test_engine_exposes_a_single_game_state_instance(self):
        board = TextBoard(["wK ."])
        engine = GameEngine(board, cell_size=100)
        assert isinstance(engine.state, GameState)
        assert engine.state.board is board

    def test_board_alias_reflects_state(self):
        board = TextBoard(["wK ."])
        engine = GameEngine(board, cell_size=100)
        assert engine.board is engine.state.board

    def test_game_over_alias_reflects_state(self):
        board = TextBoard(["wR . .", "bK . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        engine.handle_click(0, 0)    # select wR
        engine.handle_click(0, 100)  # capture bK
        engine.tick(1000)
        assert engine.game_over is engine.state.game_over is True

    def test_winner_alias_reflects_state(self):
        board = TextBoard(["wR . .", "bK . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        engine.handle_click(0, 0)
        engine.handle_click(0, 100)
        engine.tick(1000)
        assert engine.winner is engine.state.winner

    def test_pending_alias_reflects_state(self):
        board = TextBoard(["wK . ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)  # queue wK -> (0,1)
        assert engine._pending == engine.state.pending
        assert len(engine._pending) == 1

    def test_airborne_alias_reflects_state(self):
        board = TextBoard([". . .", ". wK .", ". . ."])
        engine = GameEngine(board, cell_size=100, jump_duration=1000)
        engine.handle_jump(150, 150)
        assert engine._airborne == engine.state.airborne
        assert len(engine._airborne) == 1

    def test_current_time_lives_on_state(self):
        board = TextBoard(["wK ."])
        engine = GameEngine(board, cell_size=100)
        engine.tick(250)
        assert engine.state.current_time == 250
        assert engine.clock_ms == 250
