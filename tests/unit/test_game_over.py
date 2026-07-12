"""
Unit tests for game-over behaviour (Kung Fu Chess, Iteration 7).

Two layers under test:

  * ``engine.game_over.KingCaptureRule`` in isolation — pure function of a
    board, no engine involved (mirrors how ``MoveValidator`` is tested
    separately from ``GameEngine`` in test_rules.py).
  * ``GameEngine`` wiring — the rule is checked after every ``tick()``;
    once it reports the game is over, ``handle_click`` becomes a no-op and
    a single ``GameOverEvent`` fires.

Boards that never had both Kings to begin with (used throughout the other
unit-test files for isolated movement tests) must NOT be affected by this
feature at all — see TestGameOverRuleIsNotArmedWithoutBothKings.
"""

from __future__ import annotations

from typing import List

from core.models import Color, GameResult, Position
from engine.board import TextBoard
from engine.game import GameEngine
from engine.game_over import GameOverRule, KingCaptureRule
from ui.events import GameEvent, GameOverEvent, MoveCompletedEvent, Observer


class _RecordingObserver(Observer):
    def __init__(self) -> None:
        self.events: List[GameEvent] = []

    def on_event(self, event: GameEvent) -> None:
        self.events.append(event)

    def of_type(self, cls: type) -> List[GameEvent]:
        return [e for e in self.events if isinstance(e, cls)]


# ===========================================================================
# KingCaptureRule — pure board-state checks
# ===========================================================================
#
# The rule is stateful: its first ``check()`` call PRIMES which colours
# are "armed" (had a King on that very board). GameEngine always primes
# with the pristine starting position at construction, before any move
# runs — these tests replicate that same priming-then-check sequence.
# ===========================================================================

class TestKingCaptureRule:
    def test_both_kings_present_is_not_over(self):
        board = TextBoard(["wK . .", ". . .", "bK . ."])
        result = KingCaptureRule().check(board)
        assert result == GameResult(is_over=False)

    def test_black_king_captured_after_priming_white_wins(self):
        rule = KingCaptureRule()
        rule.check(TextBoard(["wK . .", ". . .", "bK . ."]))  # prime: both armed
        result = rule.check(TextBoard(["wK . .", ". . .", ". . ."]))
        assert result.is_over is True
        assert result.winner is Color.WHITE

    def test_white_king_captured_after_priming_black_wins(self):
        rule = KingCaptureRule()
        rule.check(TextBoard(["wK . .", ". . .", "bK . ."]))  # prime: both armed
        result = rule.check(TextBoard([". . .", ". . .", "bK . ."]))
        assert result.is_over is True
        assert result.winner is Color.BLACK

    def test_both_kings_captured_after_priming_is_a_draw(self):
        rule = KingCaptureRule()
        rule.check(TextBoard(["wK . .", ". . .", "bK . ."]))  # prime: both armed
        result = rule.check(TextBoard([". . .", ". . .", ". . ."]))
        assert result.is_over is True
        assert result.winner is None

    def test_colour_that_never_started_with_a_king_cannot_end_the_game(self):
        """The first check() call IS the priming call — a board with only
        one King permanently disarms the colour that has none."""
        rule = KingCaptureRule()
        result = rule.check(TextBoard(["wK . .", ". . .", ". . ."]))
        assert result.is_over is False

    def test_priming_uses_only_the_first_check_call(self):
        """A colour that starts unarmed stays unarmed even if a King of
        that colour later appears on the board (e.g. promotion) — priming
        happens once, on the very first check()."""
        rule = KingCaptureRule()
        rule.check(TextBoard(["wK . .", ". . .", ". . ."]))  # primes black unarmed
        result = rule.check(TextBoard(["wK . .", ". . .", "bK . ."]))
        assert result.is_over is False

    def test_king_capture_rule_is_a_game_over_rule(self):
        assert isinstance(KingCaptureRule(), GameOverRule)


# ===========================================================================
# GameEngine wiring — the rule armed at construction, checked on tick()
# ===========================================================================

class TestGameOverEndsTheGame:
    def _engine(self) -> GameEngine:
        board = TextBoard(["wR . .", ". . .", "bK . ."])
        return GameEngine(board, cell_size=100, move_duration=1000)

    def test_capturing_enemy_king_sets_game_over(self):
        engine = self._engine()
        engine.handle_click(0, 0)    # select wR (0,0)
        engine.handle_click(0, 200)  # queue wR -> (2,0), capturing bK
        engine.tick(2000)
        assert engine.game_over is True

    def test_capturing_enemy_king_sets_the_winner(self):
        engine = self._engine()
        engine.handle_click(0, 0)
        engine.handle_click(0, 200)
        engine.tick(2000)
        assert engine.winner is Color.WHITE

    def test_game_not_over_while_both_kings_survive(self):
        engine = self._engine()
        engine.handle_click(0, 0)
        engine.handle_click(200, 0)  # sideways, no capture
        engine.tick(2000)
        assert engine.game_over is False
        assert engine.winner is None

    def test_game_over_fires_exactly_one_game_over_event(self):
        engine = self._engine()
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.handle_click(0, 0)
        engine.handle_click(0, 200)
        engine.tick(2000)
        engine.tick(1000)  # further ticks must not re-fire it
        game_over_events = obs.of_type(GameOverEvent)
        assert len(game_over_events) == 1
        assert game_over_events[0].winner is Color.WHITE

    def test_capturing_move_still_fires_its_own_move_completed_event(self):
        """Game-over is a side effect layered on top of normal move
        resolution — the capturing move itself still completes normally."""
        engine = self._engine()
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.handle_click(0, 0)
        engine.handle_click(0, 200)
        engine.tick(2000)
        completed = obs.of_type(MoveCompletedEvent)
        assert len(completed) == 1
        assert completed[0].piece == "wR"
        assert completed[0].to_pos == Position(2, 0)


class TestGameOverBlocksLaterClicks:
    def _engine_after_game_over(self) -> GameEngine:
        board = TextBoard(["wR . .", ". . .", "bK . wN"])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        engine.handle_click(0, 0)    # select wR
        engine.handle_click(0, 200)  # capture bK at (2,0)
        engine.tick(2000)
        assert engine.game_over is True
        return engine

    def test_click_after_game_over_does_not_select(self):
        engine = self._engine_after_game_over()
        engine.handle_click(200, 200)  # attempt to select wN at (2,2)
        assert engine.selection is None

    def test_click_after_game_over_does_not_queue_a_move(self):
        engine = self._engine_after_game_over()
        engine.handle_click(200, 200)  # select attempt (ignored)
        engine.handle_click(100, 200)  # move attempt (ignored)
        assert engine._pending == []

    def test_board_is_unchanged_by_post_game_over_clicks(self):
        engine = self._engine_after_game_over()
        before = engine.board.get_rows()
        engine.handle_click(200, 200)
        engine.handle_click(100, 200)
        engine.tick(1000)
        assert engine.board.get_rows() == before

    def test_existing_selection_before_game_over_is_irrelevant_afterward(self):
        """Even a piece that was already validly selected before the
        game-ending tick cannot be used to queue a move afterward."""
        board = TextBoard(["wR . .", ". wN .", "bK . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        engine.handle_click(100, 100)  # select wN — held across the tick
        engine.handle_click(0, 0)      # (re)select wR instead
        engine.handle_click(0, 200)    # queue capture of bK
        engine.tick(2000)              # game ends
        assert engine.game_over is True
        engine.handle_click(100, 100)  # attempt fresh selection of wN
        assert engine.selection is None


class TestGameOverRuleIsNotArmedWithoutBothKings:
    """Boards used by other unit-test files often contain only one piece.
    The game-over feature must be a complete no-op for them."""

    def test_lone_king_board_never_ends_the_game(self):
        board = TextBoard(["wK . .", ". . .", ". . ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)
        engine.tick(500)
        assert engine.game_over is False
        assert engine.board.get_piece_at(Position(0, 1)) == "wK"

    def test_board_with_no_kings_at_all_never_ends_the_game(self):
        board = TextBoard(["wR . .", ". . .", "bR . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        engine.handle_click(0, 0)
        engine.handle_click(0, 200)  # wR (0,0) captures bR (2,0)
        engine.tick(2000)
        assert engine.game_over is False
        assert engine.board.get_piece_at(Position(2, 0)) == "wR"

    def test_clicks_still_work_normally_on_a_kingless_board(self):
        board = TextBoard(["wR . .", ". . .", ". . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        engine.handle_click(0, 0)
        engine.handle_click(100, 0)
        assert engine.selection is None
        assert len(engine._pending) == 1


class TestGameOverRuleDependencyInjection:
    """GameEngine accepts a custom GameOverRule the same way it accepts a
    custom MoveValidator — constructor injection, Strategy pattern."""

    def test_custom_rule_is_used_instead_of_king_capture(self):
        class _NeverOver(GameOverRule):
            def check(self, board):
                return GameResult(is_over=False)

        board = TextBoard(["wR . .", ". . .", "bK . ."])
        engine = GameEngine(
            board, cell_size=100, move_duration=1000, game_over_rule=_NeverOver()
        )
        engine.handle_click(0, 0)
        engine.handle_click(0, 200)  # would capture bK under the default rule
        engine.tick(2000)
        assert engine.game_over is False

    def test_custom_rule_can_end_the_game_immediately(self):
        class _AlwaysOver(GameOverRule):
            def check(self, board):
                return GameResult(is_over=True, winner=Color.BLACK)

        board = TextBoard(["wR . .", ". . .", ". . ."])
        engine = GameEngine(
            board, cell_size=100, move_duration=1000, game_over_rule=_AlwaysOver()
        )
        engine.tick(0)
        assert engine.game_over is True
        assert engine.winner is Color.BLACK
