"""
Unit tests for ui/events.py

Covers: GameEvent, RenderEvent, Observer ABC.
"""

from __future__ import annotations

import pytest
from dataclasses import FrozenInstanceError

from ui.events import GameEvent, Observer, RenderEvent


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
