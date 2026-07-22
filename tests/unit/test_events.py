"""
Unit tests for ui/events.py

Covers: GameEvent, RenderEvent, Observer ABC, and to_dict() serialization
for every GameEvent subclass (see each subclass's own to_dict() override).
"""

from __future__ import annotations

import json

import pytest
from dataclasses import FrozenInstanceError

from core.models import Color, Position
from ui.events import (
    AirborneCaptureEvent,
    GameEvent,
    GameOverEvent,
    JumpLandedEvent,
    MoveCompletedEvent,
    Observer,
    RenderEvent,
    TimeAdvancedEvent,
)


# ---------------------------------------------------------------------------
# Concrete observer for testing
# ---------------------------------------------------------------------------

class _RecordingObserver(Observer):
    def __init__(self) -> None:
        self.received: list[GameEvent] = []

    def on_event(self, event: GameEvent) -> None:
        self.received.append(event)


# ===========================================================================
# RenderEvent
# ===========================================================================

class TestRenderEvent:
    def test_board_text_stored(self):
        e = RenderEvent(board_text="wK\n")
        assert e.board_text == "wK\n"

    def test_is_game_event(self):
        assert isinstance(RenderEvent(board_text=""), GameEvent)

    def test_frozen_raises_on_mutation(self):
        e = RenderEvent(board_text="x")
        with pytest.raises(FrozenInstanceError):
            e.board_text = "y"  # type: ignore[misc]

    def test_equality_same_text(self):
        assert RenderEvent("abc") == RenderEvent("abc")

    def test_inequality_different_text(self):
        assert RenderEvent("abc") != RenderEvent("xyz")

    def test_hashable(self):
        s = {RenderEvent("a"), RenderEvent("b"), RenderEvent("a")}
        assert len(s) == 2


# ===========================================================================
# Observer ABC
# ===========================================================================

class TestObserver:
    def test_abstract_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            Observer()  # type: ignore[abstract]

    def test_concrete_receives_event(self):
        obs = _RecordingObserver()
        e = RenderEvent(board_text="hello")
        obs.on_event(e)
        assert obs.received == [e]

    def test_concrete_receives_multiple_events(self):
        obs = _RecordingObserver()
        events = [RenderEvent("a"), RenderEvent("b"), RenderEvent("c")]
        for ev in events:
            obs.on_event(ev)
        assert obs.received == events


# ===========================================================================
# to_dict() serialization — every GameEvent subclass
# ===========================================================================
#
# Each test checks: the "type" field names the concrete subclass, every
# field round-trips with the correct value (Positions as plain
# {"row": int, "col": int} dicts, not raw Position objects), and the
# whole dict survives json.dumps/json.loads unchanged.
# ===========================================================================

class TestRenderEventToDict:
    def test_to_dict_shape(self):
        e = RenderEvent(board_text="wK\n")
        assert e.to_dict() == {"type": "RenderEvent", "board_text": "wK\n"}

    def test_json_round_trip(self):
        d = RenderEvent(board_text="wK\n").to_dict()
        assert json.loads(json.dumps(d)) == d


class TestTimeAdvancedEventToDict:
    def test_to_dict_shape(self):
        e = TimeAdvancedEvent(current_time=1500)
        assert e.to_dict() == {"type": "TimeAdvancedEvent", "current_time": 1500}

    def test_json_round_trip(self):
        d = TimeAdvancedEvent(current_time=1500).to_dict()
        assert json.loads(json.dumps(d)) == d


class TestMoveCompletedEventToDict:
    def test_to_dict_shape(self):
        e = MoveCompletedEvent(
            piece="wP",
            from_pos=Position(6, 0),
            to_pos=Position(4, 0),
            arrival_time=1000,
        )
        assert e.to_dict() == {
            "type": "MoveCompletedEvent",
            "piece": "wP",
            "from_pos": {"row": 6, "col": 0},
            "to_pos": {"row": 4, "col": 0},
            "arrival_time": 1000,
        }

    def test_json_round_trip(self):
        d = MoveCompletedEvent(
            piece="wP", from_pos=Position(6, 0), to_pos=Position(4, 0), arrival_time=1000
        ).to_dict()
        assert json.loads(json.dumps(d)) == d


class TestGameOverEventToDict:
    def test_to_dict_shape_with_a_winner(self):
        e = GameOverEvent(winner=Color.WHITE)
        assert e.to_dict() == {"type": "GameOverEvent", "winner": "w"}

    def test_to_dict_shape_for_a_draw(self):
        e = GameOverEvent(winner=None)
        assert e.to_dict() == {"type": "GameOverEvent", "winner": None}

    def test_json_round_trip(self):
        d = GameOverEvent(winner=Color.BLACK).to_dict()
        assert json.loads(json.dumps(d)) == d

    def test_json_round_trip_for_a_draw(self):
        d = GameOverEvent(winner=None).to_dict()
        assert json.loads(json.dumps(d)) == d


class TestJumpLandedEventToDict:
    def test_to_dict_shape(self):
        e = JumpLandedEvent(piece="wN", pos=Position(3, 3), land_time=2000)
        assert e.to_dict() == {
            "type": "JumpLandedEvent",
            "piece": "wN",
            "pos": {"row": 3, "col": 3},
            "land_time": 2000,
        }

    def test_json_round_trip(self):
        d = JumpLandedEvent(piece="wN", pos=Position(3, 3), land_time=2000).to_dict()
        assert json.loads(json.dumps(d)) == d


class TestAirborneCaptureEventToDict:
    def test_to_dict_shape(self):
        e = AirborneCaptureEvent(defender="bP", pos=Position(2, 2), attacker="wN")
        assert e.to_dict() == {
            "type": "AirborneCaptureEvent",
            "defender": "bP",
            "pos": {"row": 2, "col": 2},
            "attacker": "wN",
        }

    def test_json_round_trip(self):
        d = AirborneCaptureEvent(defender="bP", pos=Position(2, 2), attacker="wN").to_dict()
        assert json.loads(json.dumps(d)) == d
