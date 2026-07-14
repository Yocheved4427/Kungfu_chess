"""
Unit tests for the post-landing Cooldown feature (Kungfu Chess).

After a piece lands — either a normal/stop-short move arrival or a jump
landing — it must sit in a cooldown window (``COOLDOWN_DURATION`` ms,
default 1000) during which it cannot be selected, moved, or jumped
again. Overlapping mechanisms it's distinct from:
  - transit lock (``is_in_transit``): lifts the instant a move arrives,
    before cooldown even starts.
  - airborne (``is_airborne``): lifts the instant a jump lands, before
    cooldown even starts.

Board used in most tests (3×3, cell_size=100):
    row 0: "wK . ."
    row 1: ".  . ."
    row 2: ".  . ."
  wK starts at (0,0). move_duration=500 ms/cell, cooldown_duration=1000
  unless stated otherwise.

GameEngine owns no state of its own (Iteration 15) — every test builds
its own ``GameState`` and passes it explicitly to every engine call.
"""

from __future__ import annotations

from core.config import COOLDOWN_DURATION
from core.models import Position
from engine.board import TextBoard
from engine.game import GameEngine
from engine.game_state import GameState


_ROWS_3x3 = ["wK . .", ". . .", ". . ."]


def _engine_3x3(**kwargs) -> tuple[GameEngine, GameState]:
    board = TextBoard(_ROWS_3x3)
    engine = GameEngine(board, cell_size=100, move_duration=500, **kwargs)
    return engine, GameState(board=board)


class TestConfigDefault:
    def test_default_cooldown_duration_is_used_when_not_overridden(self):
        engine, _ = _engine_3x3()
        assert engine._cooldown_duration == COOLDOWN_DURATION


class TestIsInCooldownAfterMove:
    def test_not_in_cooldown_before_any_move(self):
        engine, state = _engine_3x3()
        assert engine.is_in_cooldown(state, Position(0, 0)) is False

    def test_in_cooldown_immediately_after_arrival(self):
        engine, state = _engine_3x3()
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 100, 0)  # wK -> (0,1), arrives at 500 ms
        engine.tick(state, 500)
        assert engine.is_in_cooldown(state, Position(0, 1)) is True

    def test_still_in_cooldown_one_ms_before_expiry(self):
        engine, state = _engine_3x3()
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 100, 0)  # arrives at 500 ms, cooldown until 1500 ms
        engine.tick(state, 500)
        engine.tick(state, 999)  # clock = 1499
        assert engine.is_in_cooldown(state, Position(0, 1)) is True

    def test_cooldown_expired_exactly_at_expiry_tick(self):
        engine, state = _engine_3x3()
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 100, 0)  # arrives at 500 ms, cooldown until 1500 ms
        engine.tick(state, 500)
        engine.tick(state, 1000)  # clock = 1500
        assert engine.is_in_cooldown(state, Position(0, 1)) is False

    def test_origin_cell_is_not_in_cooldown_after_piece_relocates(self):
        engine, state = _engine_3x3()
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 100, 0)  # wK -> (0,1)
        engine.tick(state, 500)
        assert engine.is_in_cooldown(state, Position(0, 0)) is False


class TestCooldownBlocksSelectionAndMoves:
    def test_click_on_cooling_down_piece_does_not_select_it(self):
        engine, state = _engine_3x3()
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 100, 0)  # arrives at 500 ms
        engine.tick(state, 500)
        engine.handle_click(state, 100, 0)  # attempt to select — still cooling down
        assert engine.selection is None

    def test_is_selectable_false_while_cooling_down(self):
        engine, state = _engine_3x3()
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 100, 0)
        engine.tick(state, 500)
        assert engine.is_selectable(state, Position(0, 1)) is False

    def test_attempt_move_rejected_while_cooling_down(self):
        engine, state = _engine_3x3()
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 100, 0)  # wK -> (0,1), arrives at 500 ms
        engine.tick(state, 500)
        assert engine.attempt_move(state, Position(0, 1), Position(0, 2)) is False
        assert state.pending == []

    def test_handle_jump_rejected_while_cooling_down(self):
        engine, state = _engine_3x3()
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 100, 0)  # wK -> (0,1), arrives at 500 ms
        engine.tick(state, 500)
        engine.handle_jump(state, 100, 0)  # attempt jump — still cooling down
        assert state.airborne == []


class TestPieceUsableAgainAfterCooldownElapses:
    def test_is_selectable_true_once_cooldown_elapses(self):
        engine, state = _engine_3x3()
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 100, 0)
        engine.tick(state, 500)
        engine.tick(state, 1000)  # clock = 1500
        assert engine.is_selectable(state, Position(0, 1)) is True

    def test_attempt_move_accepted_once_cooldown_elapses(self):
        engine, state = _engine_3x3()
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 100, 0)  # wK -> (0,1), arrives at 500 ms
        engine.tick(state, 500)
        engine.tick(state, 1000)  # clock = 1500, cooldown elapsed
        assert engine.attempt_move(state, Position(0, 1), Position(0, 2)) is True
        assert len(state.pending) == 1

    def test_handle_jump_accepted_once_cooldown_elapses(self):
        engine, state = _engine_3x3()
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 100, 0)  # wK -> (0,1), arrives at 500 ms
        engine.tick(state, 500)
        engine.tick(state, 1000)  # clock = 1500, cooldown elapsed
        engine.handle_jump(state, 100, 0)
        assert engine.is_airborne(state, Position(0, 1)) is True


class TestCooldownAfterJumpLanding:
    def test_in_cooldown_immediately_after_jump_lands(self):
        board = TextBoard([". . .", ". wK .", ". . ."])
        engine = GameEngine(board, cell_size=100, jump_duration=1000)
        state = GameState(board=board)
        engine.handle_jump(state, 150, 150)
        engine.tick(state, 1000)  # lands at t=1000
        assert engine.is_in_cooldown(state, Position(1, 1)) is True
        assert engine.is_airborne(state, Position(1, 1)) is False

    def test_selectable_again_once_landing_cooldown_elapses(self):
        board = TextBoard([". . .", ". wK .", ". . ."])
        engine = GameEngine(board, cell_size=100, jump_duration=1000)
        state = GameState(board=board)
        engine.handle_jump(state, 150, 150)
        engine.tick(state, 1000)  # lands at t=1000, cooldown until t=2000
        engine.tick(state, 1000)  # clock = 2000
        engine.handle_click(state, 150, 150)
        assert engine.selection == Position(1, 1)


class TestCooldownAfterStopShortMove:
    def test_piece_that_stops_short_enters_cooldown_at_the_stop_cell(self):
        """Rook A queues a short move; Rook B queues a longer one whose
        path is clear when queued but passes through where A is about to
        land. B stops one square short of A's new position instead of
        being dropped outright (see test_realtime_conflicts.py for the
        same scenario) — that's still a completed landing, so a cooldown
        must start at B's stop cell, not its original destination."""
        board = TextBoard(["wR . . . wR"])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        engine.handle_click(state, 50, 50)    # select Rook A at (0,0)
        engine.handle_click(state, 250, 50)   # queue A -> (0,2), arrival = 1000
        engine.handle_click(state, 450, 50)   # select Rook B at (0,4)
        engine.handle_click(state, 150, 50)   # queue B -> (0,1), arrival = 1500 (path clear now)
        engine.tick(state, 1500)
        assert state.board.get_piece_at(Position(0, 2)) == "wR"  # A's new spot
        assert state.board.get_piece_at(Position(0, 3)) == "wR"  # B stopped short
        assert engine.is_in_cooldown(state, Position(0, 3)) is True
        assert engine.is_in_cooldown(state, Position(0, 1)) is False  # never reached

    def test_move_rejected_outright_by_an_already_blocked_path_causes_no_cooldown(self):
        """When a friendly piece already sits on the very next square at
        queue time, the move is rejected before ever being queued (the
        ordinary path-clear check in MoveValidator.is_valid) — no landing
        occurs, so no cooldown should apply."""
        board = TextBoard(["wR wN . ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        engine.handle_click(state, 0, 0)    # select wR at (0,0)
        engine.handle_click(state, 300, 0)  # attempt slide to (0,3); wN at (0,1) blocks it now
        assert state.pending == []  # never queued
        assert state.board.get_piece_at(Position(0, 0)) == "wR"  # never moved
        assert engine.is_in_cooldown(state, Position(0, 0)) is False


class TestCustomCooldownDuration:
    def test_zero_cooldown_duration_allows_immediate_reuse(self):
        engine, state = _engine_3x3(cooldown_duration=0)
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 100, 0)  # wK -> (0,1), arrives at 500 ms
        engine.tick(state, 500)
        engine.handle_click(state, 100, 0)  # select immediately — no cooldown configured
        assert engine.selection == Position(0, 1)

    def test_custom_cooldown_duration_is_respected(self):
        engine, state = _engine_3x3(cooldown_duration=2000)
        engine.handle_click(state, 0, 0)
        engine.handle_click(state, 100, 0)  # wK -> (0,1), arrives at 500 ms
        engine.tick(state, 500)
        engine.tick(state, 1000)  # clock = 1500 — would have elapsed under the default
        assert engine.is_in_cooldown(state, Position(0, 1)) is True
        engine.tick(state, 1000)  # clock = 2500, past the custom 2000 ms window
        assert engine.is_in_cooldown(state, Position(0, 1)) is False
