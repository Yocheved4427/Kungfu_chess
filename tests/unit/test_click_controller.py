"""
Unit tests for controllers/click_controller.py

Scope: ClickController against a real GameEngine (so "forwards to
GameEngine.try_move" is exercised for real, not mocked) — but the focus
here is entirely on click SEMANTICS (what a click means), not move
legality itself (that's RuleEngine's job, covered in test_rule_engine.py).

The three rules from the spec:
  1. First click on a piece -> select it.
  2. First click on an empty cell (nothing selected) -> no-op.
  3. Click on a cell while a piece is selected -> attempt to move the
     selected piece there (legality decided entirely by GameEngine, via
     RuleEngine). A successful attempt applies IMMEDIATELY — try_move
     has no queueing, no arrival_time, no waiting on tick().

Plus the pre-existing nuances GameEngine.handle_click already had before
this refactor (busy pieces, friendly reselect, game-over) — this class
must reproduce them exactly, just from a separate component. Busy
(in-transit/airborne) states can no longer be created BY a click (a
completing click applies instantly), so those setups now use
engine.attempt_move()/handle_jump() directly — the older real-time
pipeline both methods still fully support, just not click-driven
anymore — while the assertions under test remain about click behavior.
"""

from __future__ import annotations

from controllers.click_controller import ClickController
from core.models import Position
from engine.board import TextBoard
from engine.board_mapper import BoardMapper
from engine.game import GameEngine
from engine.rule_engine import MoveResult, RuleEngine


def _controller(board: TextBoard, cell_size: int = 100, **engine_kwargs) -> tuple[GameEngine, ClickController]:
    engine = GameEngine(board, cell_size=cell_size, **engine_kwargs)
    controller = ClickController(engine, BoardMapper(cell_size))
    return engine, controller


# ===========================================================================
# Rule 1: first click on a piece selects it
# ===========================================================================

class TestFirstClickSelectsAPiece:
    def test_click_on_a_piece_selects_it(self):
        engine, ctrl = _controller(TextBoard(["wK . ."]))
        ctrl.handle_click(0, 0)
        assert ctrl.selection == Position(0, 0)

    def test_selecting_does_not_touch_the_board(self):
        board = TextBoard(["wK . ."])
        engine, ctrl = _controller(board)
        ctrl.handle_click(0, 0)
        assert board.get_piece_at(Position(0, 0)) == "wK"

    def test_cannot_select_a_busy_in_transit_piece(self):
        """A piece can only be "in transit" via attempt_move (the older,
        no-longer-click-driven real-time pipeline) — a click can't
        create that state anymore, since try_move applies instantly."""
        board = TextBoard(["wR . ."])
        engine, ctrl = _controller(board, move_duration=1000)
        engine.attempt_move(Position(0, 0), Position(0, 2))  # now in transit
        ctrl.handle_click(50, 50)    # attempt to select the in-transit wR
        assert ctrl.selection is None

    def test_cannot_select_an_airborne_piece(self):
        engine, ctrl = _controller(TextBoard(["wK . ."]))
        engine.handle_jump(0, 0)     # engine's own jump API, unaffected by controller
        ctrl.handle_click(0, 0)
        assert ctrl.selection is None


# ===========================================================================
# Rule 2: first click on an empty cell is a no-op
# ===========================================================================

class TestFirstClickOnEmptyCellIsNoOp:
    def test_click_on_empty_cell_selects_nothing(self):
        engine, ctrl = _controller(TextBoard([". . ."]))
        ctrl.handle_click(100, 0)
        assert ctrl.selection is None

    def test_click_out_of_bounds_is_a_no_op(self):
        engine, ctrl = _controller(TextBoard(["wK ."]))
        ctrl.handle_click(999, 999)
        assert ctrl.selection is None


# ===========================================================================
# Rule 3: click while a piece is selected -> forward a move attempt,
# applied immediately via GameEngine.try_move
# ===========================================================================

class TestSelectedClickForwardsAMoveAttempt:
    def test_legal_move_is_applied_immediately(self):
        board = TextBoard(["wR . ."])
        engine, ctrl = _controller(board)
        ctrl.handle_click(50, 50)    # select wR
        ctrl.handle_click(250, 50)   # attempt move to (0,2) — applies now
        assert board.get_piece_at(Position(0, 0)) == "."
        assert board.get_piece_at(Position(0, 2)) == "wR"

    def test_legal_move_does_not_queue_anything(self):
        """No PendingMove is ever created via try_move — the move either
        already happened or it didn't."""
        board = TextBoard(["wR . ."])
        engine, ctrl = _controller(board)
        ctrl.handle_click(50, 50)
        ctrl.handle_click(250, 50)
        assert engine._pending == []

    def test_illegal_move_is_rejected_board_unchanged(self):
        board = TextBoard(["wR bP ."])
        engine, ctrl = _controller(board)
        ctrl.handle_click(50, 50)    # select wR
        ctrl.handle_click(250, 50)   # blocked path — illegal
        assert board.get_piece_at(Position(0, 0)) == "wR"

    def test_selection_cleared_after_a_successful_attempt(self):
        board = TextBoard(["wR . ."])
        engine, ctrl = _controller(board)
        ctrl.handle_click(50, 50)
        ctrl.handle_click(250, 50)
        assert ctrl.selection is None

    def test_selection_cleared_after_a_rejected_attempt_too(self):
        """The controller doesn't know or care WHY a move failed — it
        clears selection unconditionally, exactly as GameEngine's
        original handle_click always did."""
        board = TextBoard(["wR bP ."])
        engine, ctrl = _controller(board)
        ctrl.handle_click(50, 50)
        ctrl.handle_click(250, 50)   # illegal (blocked)
        assert ctrl.selection is None

    def test_clicking_an_enemy_piece_is_a_move_attempt_not_a_reselect(self):
        board = TextBoard(["wR bN ."])
        engine, ctrl = _controller(board)
        ctrl.handle_click(50, 50)    # select wR
        ctrl.handle_click(150, 50)   # click enemy bN — capture attempt
        assert board.get_piece_at(Position(0, 1)) == "wR"

    def test_controller_never_decides_legality_itself(self):
        """The controller must not decide legality — verified by giving
        the engine a RuleEngine that rejects everything and confirming
        the controller still just forwards and reacts by clearing
        selection, regardless of the MoveResult."""

        class _AlwaysIllegal(RuleEngine):
            def validate_move(self, *args, **kwargs) -> MoveResult:
                return MoveResult.ILLEGAL_PATTERN

        board = TextBoard(["wR . ."])
        engine, ctrl = _controller(board, rule_engine=_AlwaysIllegal())
        ctrl.handle_click(50, 50)
        ctrl.handle_click(250, 50)
        assert board.get_piece_at(Position(0, 0)) == "wR"  # never moved
        assert ctrl.selection is None  # still cleared — controller doesn't inspect why


# ===========================================================================
# Friendly reselect (pre-existing nuance, preserved)
# ===========================================================================

class TestFriendlyReselect:
    def test_clicking_a_different_friendly_piece_switches_selection(self):
        board = TextBoard(["wK wR ."])
        engine, ctrl = _controller(board)
        ctrl.handle_click(0, 0)      # select wK
        ctrl.handle_click(100, 0)    # click friendly wR — switches, not a move
        assert ctrl.selection == Position(0, 1)
        assert board.get_piece_at(Position(0, 0)) == "wK"  # untouched

    def test_cannot_switch_to_a_busy_friendly(self):
        board = TextBoard(["wK wR ."])
        engine, ctrl = _controller(board, move_duration=1000)
        engine.attempt_move(Position(0, 1), Position(0, 2))  # wR now in transit
        ctrl.handle_click(0, 0)      # select wK
        ctrl.handle_click(100, 0)    # attempt switch to busy wR — blocked
        assert ctrl.selection == Position(0, 0)


# ===========================================================================
# Game over
# ===========================================================================

class TestGameOverStopsClicks:
    def test_click_after_game_over_is_a_no_op(self):
        board = TextBoard(["wR . .", "bK . ."])
        engine, ctrl = _controller(board)
        ctrl.handle_click(50, 50)
        ctrl.handle_click(50, 150)   # captures bK immediately — game over now
        assert engine.game_over is True
        ctrl.handle_click(0, 0)
        assert ctrl.selection is None


# ===========================================================================
# GameEngine.handle_click still delegates correctly (integration point)
# ===========================================================================

class TestGameEngineDelegatesToController:
    def test_engine_handle_click_uses_its_own_controller(self):
        engine = GameEngine(TextBoard(["wK ."]), cell_size=100)
        engine.handle_click(0, 0)
        assert engine.selection == Position(0, 0)
        assert engine._click_controller.selection == Position(0, 0)

    def test_engine_selection_property_is_read_only_view(self):
        engine = GameEngine(TextBoard(["wK ."]), cell_size=100)
        assert engine.selection is None
        engine.handle_click(0, 0)
        assert engine.selection == Position(0, 0)

    def test_engine_handle_click_moves_a_piece_instantly(self):
        board = TextBoard(["wR . ."])
        engine = GameEngine(board, cell_size=100)
        engine.handle_click(50, 50)
        engine.handle_click(250, 50)
        assert board.get_piece_at(Position(0, 2)) == "wR"
