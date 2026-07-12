"""
Unit tests for engine/game.py

Scope: GameEngine in isolation from the I/O handler.
A real TextBoard is used so we test board-engine integration at the unit level
(no I/O, no parser, no validator).

Moves are asynchronous: handle_click() only queues a PendingMove; the board
is mutated later by tick() once the clock reaches arrival_time. Transit-lock
behaviour (selecting / redirecting an in-transit piece) is covered separately
in test_transit_lock.py — this file focuses on construction, the clock,
Observer notifications, and move validation/queuing.

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

from core.config import MOVE_DURATION
from core.models import Position
from engine.board import TextBoard
from engine.game import GameEngine
from engine.rule_engine import MoveResult
from engine.rules import MoveValidator
from ui.events import (
    GameEvent,
    MoveCompletedEvent,
    RenderEvent,
    TimeAdvancedEvent,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_MINI_ROWS = ["wK .", ". bK"]   # 2×2 board


def _mini_engine() -> GameEngine:
    return GameEngine(TextBoard(_MINI_ROWS))


class _RecordingObserver:
    def __init__(self) -> None:
        self.events: list[GameEvent] = []

    def on_event(self, event: GameEvent) -> None:
        self.events.append(event)


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

    def test_default_validator_created_when_none_passed(self):
        engine = _mini_engine()
        assert isinstance(engine._validator, MoveValidator)

    def test_no_pending_moves_initially(self):
        assert _mini_engine()._pending == []

    def test_default_move_duration_from_config(self):
        engine = _mini_engine()
        assert engine._move_duration == MOVE_DURATION


# ===========================================================================
# tick()
# ===========================================================================

class TestGameEngineTick:
    def test_tick_advances_clock(self):
        engine = _mini_engine()
        engine.tick(200)
        assert engine.clock_ms == 200

    def test_tick_accumulates(self):
        engine = _mini_engine()
        engine.tick(100)
        engine.tick(300)
        assert engine.clock_ms == 400

    def test_tick_zero_does_not_change_clock(self):
        engine = _mini_engine()
        engine.tick(0)
        assert engine.clock_ms == 0

    def test_tick_fires_time_advanced_event(self):
        engine = _mini_engine()
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.tick(50)
        assert len(obs.events) == 1
        assert isinstance(obs.events[0], TimeAdvancedEvent)
        assert obs.events[0].current_time == 50

    def test_tick_with_no_pending_moves_does_not_fire_move_completed(self):
        engine = _mini_engine()
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.tick(50)
        assert not any(isinstance(e, MoveCompletedEvent) for e in obs.events)


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
# handle_click() – move queued (empty or enemy target)
# ===========================================================================

class TestGameEngineClickMovesInstantly:
    """handle_click forwards a completed selection to try_move (via
    ClickController), which applies a legal move IMMEDIATELY — no
    queueing, no arrival_time, no waiting on tick(). The older queued
    pipeline (attempt_move/tick(), covered by TestGameEngineClickQueuesMove
    equivalents that used to live here) is still fully supported — see
    test_realtime_conflicts.py / test_transit_lock.py, which now drive
    it directly via attempt_move() rather than through a click."""

    def test_click_empty_with_selection_moves_the_piece_immediately(self):
        engine = _mini_engine()
        engine.handle_click(0, 0)     # select wK at (0,0)
        engine.handle_click(100, 0)   # click empty at (0,1) → moves now
        assert engine.board.get_piece_at(Position(0, 0)) == "."
        assert engine.board.get_piece_at(Position(0, 1)) == "wK"

    def test_move_does_not_queue_a_pending_move(self):
        engine = _mini_engine()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)
        assert engine._pending == []

    def test_move_clears_selection(self):
        engine = _mini_engine()
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)
        assert engine.selection is None

    def test_click_enemy_with_selection_captures_immediately(self):
        engine = _mini_engine()
        engine.handle_click(0, 0)       # select wK at (0,0)
        engine.handle_click(100, 100)   # click bK at (1,1) → captures now
        assert engine.board.get_piece_at(Position(0, 0)) == "."
        assert engine.board.get_piece_at(Position(1, 1)) == "wK"

    def test_tick_is_not_required_for_the_move_to_apply(self):
        board = TextBoard(["wR . .", ". . .", ". . ."])
        engine = GameEngine(board, move_duration=100)
        engine.handle_click(0, 0)     # select wR
        engine.handle_click(200, 0)   # move 2 cells right — applies now
        assert engine.board.get_piece_at(Position(0, 2)) == "wR"
        assert engine.current_time == 0  # clock never advanced

    def test_move_completed_event_fires_immediately(self):
        engine = _mini_engine()
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)
        completed = [e for e in obs.events if isinstance(e, MoveCompletedEvent)]
        assert len(completed) == 1
        assert completed[0].piece == "wK"
        assert completed[0].from_pos == Position(0, 0)
        assert completed[0].to_pos == Position(0, 1)
        assert completed[0].arrival_time == engine.current_time

    def test_illegal_move_click_fires_no_move_completed_event(self):
        board = TextBoard(["wR bP ."])
        engine = GameEngine(board)
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.handle_click(0, 0)     # select wR
        engine.handle_click(200, 0)   # blocked path — illegal
        assert not any(isinstance(e, MoveCompletedEvent) for e in obs.events)
        assert engine.board.get_piece_at(Position(0, 0)) == "wR"


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
        expected = "\n".join(engine.board.get_rows())
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
# BoardRenderer — constructor DI (Strategy pattern, mirrors validator /
# game_over_rule). Board itself has no rendering method — see
# test_board_renderer.py for TextBoardRenderer's own coverage.
# ===========================================================================

class TestGameEngineRendererDI:
    def test_default_renderer_is_text_board_renderer(self):
        from engine.board_renderer import TextBoardRenderer

        engine = _mini_engine()
        assert isinstance(engine._renderer, TextBoardRenderer)

    def test_custom_renderer_is_used_for_render_events(self):
        from engine.board_renderer import BoardRenderer

        class _ShoutingRenderer(BoardRenderer):
            def render(self, board) -> str:
                return "\n".join(row.upper() for row in board.get_rows())

        board = TextBoard(["wk ."])
        engine = GameEngine(board, renderer=_ShoutingRenderer())
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.request_render()
        assert obs.events[0].board_text == "WK ."


# ===========================================================================
# BoardMapper — constructor DI (Strategy pattern, mirrors validator /
# renderer / game_over_rule). Board itself has no pixel-coordinate
# methods — see test_board_mapper.py for BoardMapper's own coverage.
# ===========================================================================

class TestGameEngineMapperDI:
    def test_cell_size_kwarg_builds_a_default_mapper(self):
        from engine.board_mapper import BoardMapper

        engine = GameEngine(TextBoard(["wK ."]), cell_size=50)
        assert isinstance(engine._mapper, BoardMapper)
        assert engine._mapper.cell_size == 50

    def test_custom_mapper_overrides_cell_size(self):
        from engine.board_mapper import BoardMapper

        # cell_size=100 is passed but ignored: an explicit mapper wins.
        mapper = BoardMapper(50)
        board = TextBoard(["wK ."])
        engine = GameEngine(board, cell_size=100, mapper=mapper)
        assert engine._mapper is mapper

    def test_custom_mapper_is_used_by_handle_click(self):
        from engine.board_mapper import BoardMapper

        board = TextBoard(["wK ."])
        engine = GameEngine(board, mapper=BoardMapper(50))
        engine.handle_click(25, 25)  # would be OOB-ish under cell_size=100
        assert engine.selection == Position(0, 0)

    def test_custom_mapper_is_used_by_handle_jump(self):
        from engine.board_mapper import BoardMapper

        board = TextBoard(["wK ."])
        engine = GameEngine(board, mapper=BoardMapper(50))
        engine.handle_jump(25, 25)
        assert engine.is_airborne(Position(0, 0)) is True


# ===========================================================================
# Move validation — invalid moves ignored
# ===========================================================================

class TestGameEngineInvalidMove:
    def test_invalid_rook_diagonal_does_not_queue_move(self):
        board = TextBoard(["wR . .", ". . .", ". . ."])
        engine = GameEngine(board)
        engine.handle_click(0, 0)    # select wR
        engine.handle_click(100, 100)  # diagonal move — invalid for Rook
        assert board.get_piece_at(Position(0, 0)) == "wR"
        assert engine._pending == []

    def test_invalid_move_clears_selection(self):
        board = TextBoard(["wR . .", ". . .", ". . ."])
        engine = GameEngine(board)
        engine.handle_click(0, 0)
        engine.handle_click(100, 100)  # invalid diagonal
        assert engine.selection is None

    def test_pawn_sideways_move_ignored(self):
        # Sideways is illegal shape for a Pawn even onto an enemy square.
        board = TextBoard(["wP bP", ". ."])
        engine = GameEngine(board)
        engine.handle_click(0, 0)    # select wP
        engine.handle_click(100, 0)  # sideways — illegal for Pawn
        assert board.get_piece_at(Position(0, 0)) == "wP"
        assert engine.selection is None
        assert engine._pending == []

    def test_pawn_forward_move_is_applied_immediately(self):
        """Pawns are fully implemented: a legal forward move IS applied.

        White's forward direction is decreasing row, so the pawn starts on
        the bottom row (row=1) and moves up to row=0 — its back rank, so
        it also promotes (see test_pawn_advanced.py for dedicated
        promotion coverage; this test only checks the move itself lands).
        """
        board = TextBoard([". .", "wP ."])
        engine = GameEngine(board)
        engine.handle_click(0, 100)  # select wP at (1,0)
        engine.handle_click(0, 0)    # forward move to (0,0) — applies now
        assert engine.board.get_piece_at(Position(1, 0)) == "."
        assert engine.board.get_piece_at(Position(0, 0)) in ("wP", "wQ")

    def test_blocked_rook_does_not_queue_move(self):
        # Rook at (0,0), blocker at (0,1), target at (0,2)
        board = TextBoard(["wR bP ."])
        engine = GameEngine(board)
        engine.handle_click(0, 0)    # select wR
        engine.handle_click(200, 0)  # target (0,2) — path blocked by bP
        assert board.get_piece_at(Position(0, 0)) == "wR"
        assert engine.selection is None
        assert engine._pending == []


# ===========================================================================
# Custom validator (DI branch coverage)
# ===========================================================================

class TestGameEngineCustomValidator:
    def test_custom_validator_is_used(self):
        """A validator that approves everything lets even sideways Pawns move."""

        class _AlwaysValid(MoveValidator):
            def is_valid(self, *args, **kwargs) -> bool:
                return True

        board = TextBoard(["wP wP"])
        engine = GameEngine(board, validator=_AlwaysValid())
        engine.handle_click(0, 0)    # select wP
        engine.handle_click(100, 0)  # normally invalid sideways — but custom says True
        engine.tick(engine._move_duration)
        assert board.get_piece_at(Position(0, 1)) == "wP"


# ===========================================================================
# attempt_move() / is_selectable() — GameEngine's legality surface for
# ClickController (see test_click_controller.py for the controller side).
# ===========================================================================

class TestIsSelectable:
    def test_piece_on_board_is_selectable(self):
        engine = GameEngine(TextBoard(["wK ."]))
        assert engine.is_selectable(Position(0, 0)) is True

    def test_empty_cell_is_not_selectable(self):
        engine = GameEngine(TextBoard(["wK ."]))
        assert engine.is_selectable(Position(0, 1)) is False

    def test_in_transit_piece_is_not_selectable(self):
        board = TextBoard(["wR . ."])
        engine = GameEngine(board, move_duration=1000)
        engine.handle_click(50, 50)
        engine.handle_click(250, 50)
        assert engine.is_selectable(Position(0, 0)) is False

    def test_airborne_piece_is_not_selectable(self):
        board = TextBoard(["wK ."])
        engine = GameEngine(board)
        engine.handle_jump(0, 0)
        assert engine.is_selectable(Position(0, 0)) is False


class TestAttemptMove:
    def test_legal_move_returns_true_and_queues(self):
        board = TextBoard(["wR . ."])
        engine = GameEngine(board, move_duration=1000)
        assert engine.attempt_move(Position(0, 0), Position(0, 2)) is True
        assert len(engine._pending) == 1

    def test_illegal_move_returns_false_and_does_not_queue(self):
        board = TextBoard(["wR . ."])
        engine = GameEngine(board)
        assert engine.attempt_move(Position(0, 0), Position(1, 1)) is False
        assert engine._pending == []

    def test_empty_origin_returns_false(self):
        engine = GameEngine(TextBoard([". . ."]))
        assert engine.attempt_move(Position(0, 0), Position(0, 1)) is False

    def test_busy_origin_returns_false(self):
        board = TextBoard(["wR . ."])
        engine = GameEngine(board, move_duration=1000)
        engine.attempt_move(Position(0, 0), Position(0, 1))  # now in transit
        assert engine.attempt_move(Position(0, 0), Position(0, 2)) is False

    def test_route_conflict_returns_false(self):
        board = TextBoard(["wR . .", ". . .", "bR . ."])
        engine = GameEngine(board, move_duration=1000)
        assert engine.attempt_move(Position(0, 0), Position(0, 2)) is True
        assert engine.attempt_move(Position(2, 0), Position(2, 2)) is False

    def test_after_game_over_returns_false(self):
        board = TextBoard(["wR . .", "bK . ."])
        engine = GameEngine(board, move_duration=1000)
        engine.attempt_move(Position(0, 0), Position(1, 0))  # captures bK
        engine.tick(1000)
        assert engine.game_over is True
        assert engine.attempt_move(Position(1, 0), Position(1, 1)) is False


# ===========================================================================
# try_move() — the synchronous, RuleEngine-backed service-layer entry
# point. GameEngine is the only component that mutates the board; here
# that mutation happens immediately (no PendingMove, no tick()).
# ===========================================================================

class TestTryMove:
    def test_legal_move_returns_ok_and_applies_immediately(self):
        board = TextBoard(["wR . ."])
        engine = GameEngine(board)
        result = engine.try_move(Position(0, 0), Position(0, 2))
        assert result == MoveResult.OK
        assert board.get_piece_at(Position(0, 0)) == "."
        assert board.get_piece_at(Position(0, 2)) == "wR"

    def test_no_tick_required_the_move_is_instant(self):
        board = TextBoard(["wR . ."])
        engine = GameEngine(board)
        engine.try_move(Position(0, 0), Position(0, 2))
        assert engine._pending == []  # nothing queued — already applied

    def test_outside_board_returns_outside_board_and_does_not_mutate(self):
        board = TextBoard(["wR . ."])
        engine = GameEngine(board)
        result = engine.try_move(Position(0, 0), Position(0, 99))
        assert result == MoveResult.OUTSIDE_BOARD
        assert board.get_piece_at(Position(0, 0)) == "wR"

    def test_empty_source_returns_empty_source(self):
        engine = GameEngine(TextBoard([". . ."]))
        result = engine.try_move(Position(0, 0), Position(0, 1))
        assert result == MoveResult.EMPTY_SOURCE

    def test_illegal_pattern_returns_illegal_pattern_and_does_not_mutate(self):
        board = TextBoard(["wR . .", ". . .", ". . ."])
        engine = GameEngine(board)
        result = engine.try_move(Position(0, 0), Position(2, 2))
        assert result == MoveResult.ILLEGAL_PATTERN
        assert board.get_piece_at(Position(0, 0)) == "wR"

    def test_friendly_fire_returns_friendly_fire(self):
        board = TextBoard(["wR wN ."])
        engine = GameEngine(board)
        result = engine.try_move(Position(0, 0), Position(0, 1))
        assert result == MoveResult.FRIENDLY_FIRE
        assert board.get_piece_at(Position(0, 1)) == "wN"

    def test_blocked_path_returns_blocked_path(self):
        board = TextBoard(["wR bN . ."])
        engine = GameEngine(board)
        result = engine.try_move(Position(0, 0), Position(0, 3))
        assert result == MoveResult.BLOCKED_PATH

    def test_capture_is_ok_and_removes_the_enemy(self):
        board = TextBoard(["wR bN ."])
        engine = GameEngine(board)
        result = engine.try_move(Position(0, 0), Position(0, 1))
        assert result == MoveResult.OK
        assert board.get_piece_at(Position(0, 1)) == "wR"

    def test_after_game_over_returns_game_over_and_does_not_mutate(self):
        board = TextBoard(["wR . .", "bK . ."])
        engine = GameEngine(board)
        engine.try_move(Position(0, 0), Position(1, 0))  # captures bK, ends game
        assert engine.game_over is True
        before = board.get_rows()
        result = engine.try_move(Position(1, 0), Position(1, 1))
        assert result == MoveResult.GAME_OVER
        assert board.get_rows() == before

    def test_king_capture_via_try_move_ends_the_game(self):
        board = TextBoard(["wR . .", "bK . ."])
        engine = GameEngine(board)
        result = engine.try_move(Position(0, 0), Position(1, 0))
        assert result == MoveResult.OK
        assert engine.game_over is True
        assert engine.winner is not None

    def test_pawn_reaching_back_rank_promotes(self):
        board = TextBoard([". .", "wP ."])
        engine = GameEngine(board)
        result = engine.try_move(Position(1, 0), Position(0, 0))
        assert result == MoveResult.OK
        assert board.get_piece_at(Position(0, 0)) == "wQ"

    def test_move_completed_event_fires_with_current_time_as_arrival(self):
        board = TextBoard(["wR . ."])
        engine = GameEngine(board)
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.tick(250)  # advance the clock first
        engine.try_move(Position(0, 0), Position(0, 1))
        completed = [e for e in obs.events if isinstance(e, MoveCompletedEvent)]
        assert len(completed) == 1
        assert completed[0].piece == "wR"
        assert completed[0].from_pos == Position(0, 0)
        assert completed[0].to_pos == Position(0, 1)
        assert completed[0].arrival_time == 250

    def test_does_not_queue_a_pending_move_on_success(self):
        board = TextBoard(["wR . ."])
        engine = GameEngine(board)
        engine.try_move(Position(0, 0), Position(0, 1))
        assert engine._pending == []

    def test_ignores_busy_state_unlike_attempt_move(self):
        """try_move deliberately does not model the real-time busy/
        in-transit rule — it's a plain RuleEngine-backed move."""
        board = TextBoard(["wR . ."])
        engine = GameEngine(board, move_duration=1000)
        engine.attempt_move(Position(0, 0), Position(0, 1))  # now "in transit"
        assert engine.is_in_transit(Position(0, 0)) is True
        result = engine.try_move(Position(0, 0), Position(0, 2))
        assert result == MoveResult.OK
        assert board.get_piece_at(Position(0, 0)) == "."
        assert board.get_piece_at(Position(0, 2)) == "wR"

    def test_custom_rule_engine_is_used(self):
        from engine.rule_engine import RuleEngine as _RuleEngine

        class _AlwaysIllegal(_RuleEngine):
            def validate_move(self, *args, **kwargs) -> MoveResult:
                return MoveResult.ILLEGAL_PATTERN

        board = TextBoard(["wR . ."])
        engine = GameEngine(board, rule_engine=_AlwaysIllegal())
        result = engine.try_move(Position(0, 0), Position(0, 1))
        assert result == MoveResult.ILLEGAL_PATTERN
        assert board.get_piece_at(Position(0, 0)) == "wR"
