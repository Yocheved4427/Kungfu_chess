"""
Unit tests for src/engine.py

Scope: GameEngine in isolation from the I/O handler.
A real TextBoard is used so we test board-engine integration at the unit level
(no I/O, no parser, no validator).

Board used in most tests (2×2):
    row 0: "wK ."
    row 1: ". bK"

  col:  0    1
row 0: wK   .
row 1: .    bK

Pixel mapping (CELL_SIZE = 100):
  handle_click(0,   0)   → (row=0, col=0) → wK  (white king)
  handle_click(100, 0)   → (row=0, col=1) → .   (empty)
  handle_click(0,   100) → (row=1, col=0) → .   (empty)
  handle_click(100, 100) → (row=1, col=1) → bK  (black king)
"""

import pytest

from src.board import TextBoard
from src.engine import GameEngine
from src.events import GameEvent, RenderEvent
from src.models import Position
from src.rules import MoveValidator


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_MINI_ROWS = ["wK .", ". bK"]   # 2×2 board


def _mini_engine() -> GameEngine:
    return GameEngine(TextBoard(_MINI_ROWS))


# ===========================================================================
# Construction
# ===========================================================================

class TestGameEngineInit:
    def test_clock_starts_at_zero(self):
        assert _mini_engine().clock_ms == 0

    def test_nothing_selected_initially(self):
        assert _mini_engine().selection is None

    def test_board_attribute_is_the_board(self):
        board = TextBoard(_MINI_ROWS)
        engine = GameEngine(board)
        assert engine.board is board


# ===========================================================================
# wait()
# ===========================================================================

class TestGameEngineWait:
    def test_wait_advances_clock(self):
        engine = _mini_engine()
        engine.wait(200)
        assert engine.clock_ms == 200

    def test_wait_accumulates(self):
        engine = _mini_engine()
        engine.wait(100)
        engine.wait(300)
        assert engine.clock_ms == 400

    def test_wait_zero_does_not_change_clock(self):
        engine = _mini_engine()
        engine.wait(0)
        assert engine.clock_ms == 0


# ===========================================================================
# handle_click() – out-of-bounds
# ===========================================================================

class TestGameEngineClickOutOfBounds:
    def test_click_row_too_large_ignored(self):
        engine = _mini_engine()
        engine.handle_click(0, 200)   # row=2 on a 2-row board
        assert engine.selection is None

    def test_click_col_too_large_ignored(self):
        engine = _mini_engine()
        engine.handle_click(200, 0)   # col=2 on a 2-col board
        assert engine.selection is None

    def test_click_negative_x_ignored(self):
        engine = _mini_engine()
        engine.handle_click(-1, 0)
        assert engine.selection is None

    def test_click_negative_y_ignored(self):
        engine = _mini_engine()
        engine.handle_click(0, -1)
        assert engine.selection is None


# ===========================================================================
# handle_click() – no selection yet
# ===========================================================================

class TestGameEngineClickNoSelection:
    def test_click_empty_with_no_selection_ignored(self):
        engine = _mini_engine()
        engine.handle_click(100, 0)   # (row=0, col=1) → empty
        assert engine.selection is None

    def test_click_piece_selects_it(self):
        engine = _mini_engine()
        engine.handle_click(0, 0)     # (row=0, col=0) → wK
        assert engine.selection == Position(0, 0)

    def test_click_black_piece_selects_it(self):
        engine = _mini_engine()
        engine.handle_click(100, 100)  # (row=1, col=1) → bK
        assert engine.selection == Position(1, 1)


# ===========================================================================
# handle_click() – friendly piece replaces selection
# ===========================================================================

class TestGameEngineClickFriendly:
    def test_click_friendly_replaces_selection(self):
        board = TextBoard(["wK wR"])
        engine = GameEngine(board)
        engine.handle_click(0, 0)    # select wK at col=0
        engine.handle_click(100, 0)  # click wR at col=1 (friendly)
        assert engine.selection == Position(0, 1)

    def test_click_friendly_does_not_move_piece(self):
        board = TextBoard(["wK wR"])
        engine = GameEngine(board)
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)
        # wK must still be in col=0
        assert board.get_piece_at(Position(0, 0)) == "wK"

    def test_click_friendly_selection_is_new_piece(self):
        board = TextBoard(["wK wR"])
        engine = GameEngine(board)
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)
        assert engine.selection == Position(0, 1)


# ===========================================================================
# handle_click() – move committed (empty or enemy target)
# ===========================================================================

class TestGameEngineClickCommitsMove:
    def test_click_empty_with_selection_moves_piece(self):
        engine = _mini_engine()
        engine.handle_click(0, 0)     # select wK at (0,0)
        engine.handle_click(100, 0)   # click empty at (0,1) → move
        assert engine.board.get_piece_at(Position(0, 0)) == "."
        assert engine.board.get_piece_at(Position(0, 1)) == "wK"

    def test_click_enemy_with_selection_captures(self):
        engine = _mini_engine()
        engine.handle_click(0, 0)       # select wK at (0,0)
        engine.handle_click(100, 100)   # click bK at (1,1) → capture
        assert engine.board.get_piece_at(Position(0, 0)) == "."
        assert engine.board.get_piece_at(Position(1, 1)) == "wK"

    def test_move_clears_selection(self):
        engine = _mini_engine()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)
        assert engine.selection is None

    def test_source_square_is_empty_after_move(self):
        engine = _mini_engine()
        engine.handle_click(0, 0)    # select wK
        engine.handle_click(0, 100)  # move to (1,0)
        assert engine.board.get_piece_at(Position(0, 0)) == "."

    def test_destination_has_piece_after_move(self):
        engine = _mini_engine()
        engine.handle_click(0, 0)
        engine.handle_click(0, 100)  # → (row=1, col=0)
        assert engine.board.get_piece_at(Position(1, 0)) == "wK"


# ===========================================================================
# _is_friendly()
# ===========================================================================

class TestIsFriendly:
    def setup_method(self):
        self.engine = _mini_engine()

    def test_same_color_white(self):
        assert self.engine._is_friendly("wK", "wR") is True

    def test_same_color_black(self):
        assert self.engine._is_friendly("bK", "bQ") is True

    def test_different_colors(self):
        assert self.engine._is_friendly("wK", "bK") is False

    def test_first_none_returns_false(self):
        assert self.engine._is_friendly(None, "wK") is False

    def test_second_none_returns_false(self):
        assert self.engine._is_friendly("wK", None) is False

    def test_both_none_returns_false(self):
        assert self.engine._is_friendly(None, None) is False


# ===========================================================================
# Observer / Subject interface
# ===========================================================================

class _RecordingObserver:
    def __init__(self) -> None:
        self.events: list[GameEvent] = []

    def on_event(self, event: GameEvent) -> None:
        self.events.append(event)


class TestGameEngineObserver:
    def test_request_render_fires_render_event(self):
        obs = _RecordingObserver()
        engine = _mini_engine()
        engine.add_observer(obs)
        engine.request_render()
        assert len(obs.events) == 1
        assert isinstance(obs.events[0], RenderEvent)

    def test_render_event_contains_board_text(self):
        engine = _mini_engine()
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.request_render()
        expected = engine.board.render()
        assert obs.events[0].board_text == expected

    def test_multiple_observers_all_notified(self):
        engine = _mini_engine()
        obs_a, obs_b = _RecordingObserver(), _RecordingObserver()
        engine.add_observer(obs_a)
        engine.add_observer(obs_b)
        engine.request_render()
        assert len(obs_a.events) == 1
        assert len(obs_b.events) == 1

    def test_request_render_twice_fires_two_events(self):
        engine = _mini_engine()
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.request_render()
        engine.request_render()
        assert len(obs.events) == 2

    def test_no_observers_request_render_does_not_crash(self):
        engine = _mini_engine()
        engine.request_render()  # should not raise


# ===========================================================================
# Move validation — invalid moves ignored
# ===========================================================================

class TestGameEngineInvalidMove:
    def test_invalid_rook_diagonal_does_not_mutate_board(self):
        board = TextBoard(["wR . .", ". . .", ". . ."])
        engine = GameEngine(board)
        engine.handle_click(0, 0)    # select wR
        engine.handle_click(100, 100)  # diagonal move — invalid for Rook
        assert board.get_piece_at(Position(0, 0)) == "wR"
        assert board.get_piece_at(Position(1, 1)) == "."

    def test_invalid_move_clears_selection(self):
        board = TextBoard(["wR . .", ". . .", ". . ."])
        engine = GameEngine(board)
        engine.handle_click(0, 0)
        engine.handle_click(100, 100)  # invalid diagonal
        assert engine.selection is None

    def test_pawn_move_not_implemented_ignores_move(self):
        board = TextBoard(["wP .", ". ."])
        engine = GameEngine(board)
        engine.handle_click(0, 0)    # select wP
        engine.handle_click(0, 100)  # try vertical move — Pawn not implemented
        assert board.get_piece_at(Position(0, 0)) == "wP"
        assert engine.selection is None

    def test_blocked_rook_does_not_move(self):
        # Rook at (0,0), blocker at (0,1), target at (0,2)
        board = TextBoard(["wR bP ."])
        engine = GameEngine(board)
        engine.handle_click(0, 0)    # select wR
        engine.handle_click(200, 0)  # target (0,2) — path blocked by bP
        assert board.get_piece_at(Position(0, 0)) == "wR"
        assert engine.selection is None


# ===========================================================================
# Custom validator (DI branch coverage)
# ===========================================================================

class TestGameEngineCustomValidator:
    def test_custom_validator_is_used(self):
        """A validator that approves everything lets even Pawns move."""

        class _AlwaysValid(MoveValidator):
            def is_valid(self, *args, **kwargs) -> bool:
                return True

        board = TextBoard(["wP .", ". ."])
        engine = GameEngine(board, validator=_AlwaysValid())
        engine.handle_click(0, 0)    # select wP
        engine.handle_click(100, 0)  # normally invalid — but custom says True
        assert board.get_piece_at(Position(0, 1)) == "wP"

    def test_default_validator_created_when_none_passed(self):
        engine = _mini_engine()
        assert isinstance(engine._validator, MoveValidator)
