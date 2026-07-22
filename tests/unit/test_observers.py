"""
Unit tests for ui/observers.py (SoundTriggerObserver, GameLifecycleObserver).

Both classes are currently pure logging hooks — no audio playback, no
client-side animation triggering (see that module's own header) — so
these tests only confirm the right message is logged for the right
event, via caplog, the same pattern test_main_gui.py already established
for logging assertions (see its own TestResolveCellSize/TestLoadBoard).
"""

from __future__ import annotations

from core.models import Color, Position
from ui.events import (
    AirborneCaptureEvent,
    GameOverEvent,
    JumpLandedEvent,
    MoveCompletedEvent,
    RenderEvent,
    TimeAdvancedEvent,
)
from ui.observers import GameLifecycleObserver, SoundTriggerObserver


class TestSoundTriggerObserver:
    def test_move_completed_logs_the_move_sound(self, caplog):
        obs = SoundTriggerObserver()
        event = MoveCompletedEvent(
            piece="wP", from_pos=Position(6, 0), to_pos=Position(4, 0), arrival_time=1000
        )

        with caplog.at_level("INFO", logger="ui.observers"):
            obs.on_event(event)

        assert "move" in caplog.text

    def test_airborne_capture_logs_the_capture_sound(self, caplog):
        obs = SoundTriggerObserver()
        event = AirborneCaptureEvent(defender="bP", pos=Position(2, 2), attacker="wN")

        with caplog.at_level("INFO", logger="ui.observers"):
            obs.on_event(event)

        assert "capture" in caplog.text

    def test_game_over_logs_the_game_over_sound(self, caplog):
        obs = SoundTriggerObserver()
        event = GameOverEvent(winner=Color.WHITE)

        with caplog.at_level("INFO", logger="ui.observers"):
            obs.on_event(event)

        assert "game-over" in caplog.text

    def test_render_event_logs_nothing(self, caplog):
        obs = SoundTriggerObserver()
        event = RenderEvent(board_text="x")

        with caplog.at_level("INFO", logger="ui.observers"):
            obs.on_event(event)

        assert caplog.text == ""

    def test_time_advanced_logs_nothing(self, caplog):
        obs = SoundTriggerObserver()
        event = TimeAdvancedEvent(current_time=500)

        with caplog.at_level("INFO", logger="ui.observers"):
            obs.on_event(event)

        assert caplog.text == ""

    def test_jump_landed_logs_nothing(self, caplog):
        """A jump landing with no capture is silent -- see the class's own
        docstring on why this event isn't in its sound mapping."""
        obs = SoundTriggerObserver()
        event = JumpLandedEvent(piece="wN", pos=Position(3, 3), land_time=2000)

        with caplog.at_level("INFO", logger="ui.observers"):
            obs.on_event(event)

        assert caplog.text == ""


class TestGameLifecycleObserver:
    def test_first_render_event_logs_game_started(self, caplog):
        obs = GameLifecycleObserver()
        event = RenderEvent(board_text="x")

        with caplog.at_level("INFO", logger="ui.observers"):
            obs.on_event(event)

        assert "started" in caplog.text

    def test_a_second_render_event_does_not_log_started_again(self, caplog):
        obs = GameLifecycleObserver()
        obs.on_event(RenderEvent(board_text="first"))

        with caplog.at_level("INFO", logger="ui.observers"):
            obs.on_event(RenderEvent(board_text="second"))

        assert caplog.text == ""

    def test_game_over_event_logs_game_over(self, caplog):
        obs = GameLifecycleObserver()
        event = GameOverEvent(winner=Color.BLACK)

        with caplog.at_level("INFO", logger="ui.observers"):
            obs.on_event(event)

        assert "game over" in caplog.text

    def test_a_fresh_instance_logs_started_again_for_a_new_game(self, caplog):
        """Confirms the per-instance 'already started' flag doesn't leak
        across instances -- each restart builds a fresh observer (see
        ui/game_factory.py's _new_game)."""
        first_game_obs = GameLifecycleObserver()
        first_game_obs.on_event(RenderEvent(board_text="game one"))

        second_game_obs = GameLifecycleObserver()
        with caplog.at_level("INFO", logger="ui.observers"):
            second_game_obs.on_event(RenderEvent(board_text="game two"))

        assert "started" in caplog.text

    def test_other_events_log_nothing(self, caplog):
        obs = GameLifecycleObserver()
        event = TimeAdvancedEvent(current_time=500)

        with caplog.at_level("INFO", logger="ui.observers"):
            obs.on_event(event)

        assert caplog.text == ""
