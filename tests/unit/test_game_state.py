"""
Unit tests for ``GameState`` (Kungfu Chess).

Covers the dataclass itself (defaults, independence between instances)
and that ``GameEngine`` — which owns no state of its own (Iteration 15)
— correctly reads and mutates an externally-supplied ``GameState``
passed explicitly into every action method. The state machine's full
*behavior* (moves, jumps, cooldowns, game over) is already covered
end-to-end elsewhere (test_engine.py, test_jump.py, test_cooldown.py,
...) — this file only checks the shape of the state container and that
GameEngine threads it through rather than holding any of its own.
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


class TestGameEngineHoldsNoState:
    """GameEngine owns no GameState of its own (Iteration 15) — every
    action method takes one explicitly, and the *same* GameEngine
    instance can drive several independent GameStates without any
    cross-talk between them."""

    def test_engine_has_no_state_attribute(self):
        engine = GameEngine(TextBoard(["wK ."]), cell_size=100)
        assert not hasattr(engine, "state")

    def test_one_engine_instance_drives_two_independent_states(self):
        engine = GameEngine(TextBoard(["wK . ."]), cell_size=100, move_duration=500)
        state_a = GameState(board=TextBoard(["wK . ."]))
        state_b = GameState(board=TextBoard(["wK . ."]))

        engine.handle_click(state_a, 0, 0)
        engine.handle_click(state_a, 100, 0)  # queue a move only in state_a

        assert len(state_a.pending) == 1
        assert state_b.pending == []  # state_b is untouched

        engine.tick(state_a, 500)
        engine.tick(state_b, 250)

        assert state_a.current_time == 500
        assert state_b.current_time == 250  # clocks advance independently


class TestGameEngineMutatesTheGivenState:
    def test_tick_advances_the_given_states_clock(self):
        engine = GameEngine(TextBoard(["wK ."]), cell_size=100)
        state = GameState(board=TextBoard(["wK ."]))
        engine.tick(state, 250)
        assert state.current_time == 250

    def test_attempt_move_queues_onto_the_given_states_pending_list(self):
        board = TextBoard(["wK . ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        assert engine.attempt_move(state, Position(0, 0), Position(0, 1)) is True
        assert len(state.pending) == 1
        assert state.pending[0].from_pos == Position(0, 0)

    def test_handle_jump_appends_to_the_given_states_airborne_list(self):
        board = TextBoard([". . .", ". wK .", ". . ."])
        engine = GameEngine(board, cell_size=100, jump_duration=1000)
        state = GameState(board=board)
        engine.handle_jump(state, 150, 150)
        assert len(state.airborne) == 1
        assert state.airborne[0].pos == Position(1, 1)

    def test_game_over_and_winner_are_written_onto_the_given_state(self):
        board = TextBoard(["wR . .", "bK . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        engine.handle_click(state, 0, 0)    # select wR
        engine.handle_click(state, 0, 100)  # capture bK
        engine.tick(state, 1000)
        assert state.game_over is True
        assert state.winner is not None
