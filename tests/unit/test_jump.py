"""
Unit tests for the Jump feature (Kung Fu Chess, Iteration 8).

Rules under test:
  1. A jump lasts JUMP_DURATION ms (default 1000).
  2. The jumping piece stays on the same logical cell — it never moves.
  3. While airborne, if an enemy PendingMove arrives at its cell, the
     airborne piece captures the arriving piece (the arriver is removed;
     the defender never moves).
  4. If no enemy arrives during the jump, the piece lands normally (no
     board mutation — it was always there).
  5. A moving piece cannot jump.
  6. A captured (i.e. absent) piece cannot jump.
"""

from __future__ import annotations

from typing import List

from core.models import Position
from engine.board import TextBoard
from engine.game import GameEngine
from ui.events import (
    AirborneCaptureEvent,
    GameEvent,
    JumpLandedEvent,
    MoveCompletedEvent,
    Observer,
)


class _RecordingObserver(Observer):
    def __init__(self) -> None:
        self.events: List[GameEvent] = []

    def on_event(self, event: GameEvent) -> None:
        self.events.append(event)

    def of_type(self, cls: type) -> List[GameEvent]:
        return [e for e in self.events if isinstance(e, cls)]


# ===========================================================================
# handle_jump() — acceptance / rejection
# ===========================================================================

class TestHandleJumpAcceptance:
    def test_jump_on_a_piece_makes_it_airborne(self):
        board = TextBoard([". . .", ". wK .", ". . ."])
        engine = GameEngine(board, cell_size=100, jump_duration=1000)
        engine.handle_jump(150, 150)
        assert engine.is_airborne(Position(1, 1)) is True

    def test_jump_land_time_is_current_time_plus_jump_duration(self):
        board = TextBoard([". . .", ". wK .", ". . ."])
        engine = GameEngine(board, cell_size=100, jump_duration=1000)
        engine.tick(500)  # clock = 500
        engine.handle_jump(150, 150)
        assert engine._airborne[0].land_time == 1500

    def test_jump_does_not_mutate_the_board(self):
        board = TextBoard([". . .", ". wK .", ". . ."])
        engine = GameEngine(board, cell_size=100)
        engine.handle_jump(150, 150)
        assert engine.board.get_piece_at(Position(1, 1)) == "wK"

    def test_jump_out_of_bounds_is_ignored(self):
        board = TextBoard(["wK ."])
        engine = GameEngine(board, cell_size=100)
        engine.handle_jump(500, 500)
        assert engine._airborne == []

    def test_jump_on_empty_square_is_ignored(self):
        """A captured piece (i.e. an empty square) cannot jump."""
        board = TextBoard([". . .", ". . .", ". . ."])
        engine = GameEngine(board, cell_size=100)
        engine.handle_jump(150, 150)
        assert engine._airborne == []

    def test_jump_does_not_touch_selection_state(self):
        board = TextBoard([". . .", ". wK .", ". . ."])
        engine = GameEngine(board, cell_size=100)
        engine.handle_click(0, 0)  # nothing there, selection stays None
        engine.handle_jump(150, 150)
        assert engine.selection is None


class TestHandleJumpRejection:
    def test_moving_piece_cannot_jump(self):
        """A piece with a pending move (mid-transit) cannot also jump."""
        board = TextBoard(["wR . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        engine.handle_click(50, 50)    # select wR
        engine.handle_click(250, 50)   # queue move -> (0,2), in transit
        engine.handle_jump(50, 50)     # attempt jump at its (still shown) origin
        assert engine._airborne == []

    def test_already_airborne_piece_cannot_jump_again(self):
        board = TextBoard([". . .", ". wK .", ". . ."])
        engine = GameEngine(board, cell_size=100, jump_duration=1000)
        engine.handle_jump(150, 150)
        engine.handle_jump(150, 150)  # second attempt — ignored
        assert len(engine._airborne) == 1

    def test_jump_after_game_over_is_ignored(self):
        board = TextBoard(["wR . .", "bK . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        engine.handle_click(0, 0)     # select wR
        engine.handle_click(0, 100)   # capture bK
        engine.tick(1000)             # game ends, White wins
        assert engine.game_over is True
        engine.handle_jump(200, 100)  # attempt jump on... nothing relevant, still guarded
        assert engine._airborne == []


class TestClickIsBlockedByAirborne:
    def test_cannot_select_an_airborne_piece(self):
        board = TextBoard([". . .", ". wK .", ". . ."])
        engine = GameEngine(board, cell_size=100)
        engine.handle_jump(150, 150)
        engine.handle_click(150, 150)
        assert engine.selection is None

    def test_cannot_switch_selection_to_an_airborne_friendly(self):
        board = TextBoard(["wK wR .", ". . ."])
        engine = GameEngine(board, cell_size=100)
        engine.handle_jump(100, 0)   # wR airborne
        engine.handle_click(0, 0)    # select wK
        engine.handle_click(100, 0)  # attempt switch to airborne wR — blocked
        assert engine.selection == Position(0, 0)

    def test_jump_between_two_clicks_cancels_the_pending_move_attempt(self):
        """Selecting a piece, then jumping it before completing the move
        click, must not let the move be queued."""
        board = TextBoard(["wR . ."])
        engine = GameEngine(board, cell_size=100, jump_duration=1000)
        engine.handle_click(50, 50)   # select wR
        engine.handle_jump(50, 50)    # wR goes airborne mid-selection
        engine.handle_click(250, 50)  # attempt to complete the move — must fail
        assert engine._pending == []
        assert engine.selection is None


# ===========================================================================
# tick() resolution: landing safely vs. airborne capture
# ===========================================================================

class TestJumpLandsSafely:
    def test_piece_still_there_after_land_time_with_no_arrival(self):
        board = TextBoard([". . .", ". wK .", ". . ."])
        engine = GameEngine(board, cell_size=100, jump_duration=1000)
        engine.handle_jump(150, 150)
        engine.tick(1000)
        assert engine.board.get_piece_at(Position(1, 1)) == "wK"
        assert engine.is_airborne(Position(1, 1)) is False

    def test_jump_landed_event_fires_on_expiry(self):
        board = TextBoard([". . .", ". wK .", ". . ."])
        engine = GameEngine(board, cell_size=100, jump_duration=1000)
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.handle_jump(150, 150)
        engine.tick(1000)
        landed = obs.of_type(JumpLandedEvent)
        assert len(landed) == 1
        assert landed[0].piece == "wK"
        assert landed[0].pos == Position(1, 1)

    def test_still_airborne_before_land_time(self):
        board = TextBoard([". . .", ". wK .", ". . ."])
        engine = GameEngine(board, cell_size=100, jump_duration=1000)
        engine.handle_jump(150, 150)
        engine.tick(999)
        assert engine.is_airborne(Position(1, 1)) is True

    def test_piece_selectable_again_immediately_after_landing(self):
        board = TextBoard([". . .", ". wK .", ". . ."])
        engine = GameEngine(board, cell_size=100, jump_duration=1000)
        engine.handle_jump(150, 150)
        engine.tick(1000)
        engine.handle_click(150, 150)
        assert engine.selection == Position(1, 1)


class TestAirborneCapture:
    """Jump-interception is exclusively an attempt_move/tick() (the older,
    queued real-time pipeline) concept — try_move (what handle_click uses
    now) has no notion of airborne pieces, so an attacker arriving at an
    airborne cell via a click would just capture it normally, defeating
    the whole point of the test. These tests drive the attacking move via
    attempt_move() directly; handle_jump() is unaffected either way."""

    def _engine(self) -> GameEngine:
        board = TextBoard([". . .", "wK bR .", ". . ."])
        return GameEngine(board, cell_size=100, move_duration=1000, jump_duration=1000)

    def test_arriving_enemy_is_removed_defender_stays(self):
        engine = self._engine()
        engine.handle_jump(50, 150)    # wK airborne at (1,0)
        engine.attempt_move(Position(1, 1), Position(1, 0))  # bR attacks airborne wK
        engine.tick(1000)
        assert engine.board.get_piece_at(Position(1, 0)) == "wK"
        assert engine.board.get_piece_at(Position(1, 1)) == "."

    def test_airborne_capture_event_fires_instead_of_move_completed(self):
        engine = self._engine()
        obs = _RecordingObserver()
        engine.add_observer(obs)
        engine.handle_jump(50, 150)
        engine.attempt_move(Position(1, 1), Position(1, 0))
        engine.tick(1000)
        captures = obs.of_type(AirborneCaptureEvent)
        assert len(captures) == 1
        assert captures[0].defender == "wK"
        assert captures[0].pos == Position(1, 0)
        assert captures[0].attacker == "bR"
        assert obs.of_type(MoveCompletedEvent) == []

    def test_defender_still_grounds_normally_after_winning(self):
        engine = self._engine()
        engine.handle_jump(50, 150)
        engine.attempt_move(Position(1, 1), Position(1, 0))
        engine.tick(1000)  # attacker arrives AND land_time both hit at t=1000
        assert engine.is_airborne(Position(1, 0)) is False
        engine.handle_click(50, 150)
        assert engine.selection == Position(1, 0)

    def test_landing_exact_tick_as_arrival_still_defends(self):
        """land_time == arrival_time: the defender is still considered
        airborne for the whole tick that grounds it (grounding happens
        after move resolution) — the attacker loses."""
        engine = self._engine()
        engine.handle_jump(50, 150)    # land_time = 1000
        engine.attempt_move(Position(1, 1), Position(1, 0))  # arrival_time = 1000
        engine.tick(1000)
        assert engine.board.get_piece_at(Position(1, 0)) == "wK"

    def test_friendly_arrival_at_airborne_cell_is_rejected_not_captured(self):
        """A same-colour piece trying to land on an airborne friendly is
        blocked by the ordinary friendly-fire rule — no special jump
        interaction needed. True for both pathways (RuleEngine and
        MoveValidator both reject friendly-fire), so this one still
        works driven through a click."""
        board = TextBoard([". . .", "wK wR .", ". . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        engine.handle_jump(50, 150)    # wK airborne
        engine.handle_click(150, 150)  # select wR
        engine.handle_click(50, 150)   # attempt to land on friendly wK — rejected instantly
        assert engine.board.get_piece_at(Position(1, 0)) == "wK"
        assert engine.board.get_piece_at(Position(1, 1)) == "wR"

    def test_multiple_enemies_arriving_same_tick_are_all_defeated(self):
        """The airborne piece never leaves its cell, so it can defeat more
        than one arrival within the same tick."""
        board = TextBoard(["bR . .", "wK . .", "bR . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000, jump_duration=1000)
        engine.handle_jump(0, 100)     # wK airborne at (1,0)
        engine.attempt_move(Position(0, 0), Position(1, 0))  # bR #1, 1 cell
        engine.attempt_move(Position(2, 0), Position(1, 0))  # bR #2, 1 cell
        engine.tick(1000)
        assert engine.board.get_piece_at(Position(1, 0)) == "wK"
        assert engine.board.get_piece_at(Position(0, 0)) == "."
        assert engine.board.get_piece_at(Position(2, 0)) == "."

    def test_jump_too_late_after_move_already_landed_captures_normally(self):
        """A click-driven capture now applies instantly (try_move), so
        by the time the jump command runs the attacker has already
        landed — the jump command simply jumps the survivor.

        Uses a Knight rather than a King so the capture doesn't end the
        game (see TestAirborneCaptureEndsGameViaKing for that scenario).
        """
        board = TextBoard([". . .", "wN bR .", ". . ."])
        engine = GameEngine(board, cell_size=100)
        engine.handle_click(150, 150)  # select bR
        engine.handle_click(50, 150)   # bR captures wN immediately
        engine.handle_jump(50, 150)    # too late: (1,0) now holds bR, jumping it now
        assert engine.board.get_piece_at(Position(1, 0)) == "bR"
        assert engine._airborne[0].piece == "bR"  # jumps the survivor, not the dead wN


class TestAirborneCaptureEndsGameViaKing:
    def test_king_removed_by_airborne_capture_ends_the_game(self):
        board = TextBoard([". . .", "bR wK .", ". . bN"])
        engine = GameEngine(board, cell_size=100, move_duration=1000, jump_duration=1000)
        engine.handle_jump(0, 100)     # bR airborne at (1,0)
        engine.attempt_move(Position(1, 1), Position(1, 0))  # wK attacks airborne bR
        engine.tick(1000)
        assert engine.game_over is True
        assert engine.board.get_piece_at(Position(1, 0)) == "bR"
        # Later click on the surviving wN must now be ignored.
        engine.handle_click(200, 200)
        assert engine.selection is None
