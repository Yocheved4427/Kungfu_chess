"""
Unit tests for ui/bus.py

Scope: Bus in isolation from GameEngine — GameEngine now delegates
add_observer()/_notify() to a Bus instance internally (see engine/game.py),
but its own extensive observer-notification coverage (test_engine.py and
friends) already exercises that delegation end-to-end. This file tests
Bus's own subscribe()/publish() contract directly, the same "test the
component in isolation" convention test_board_mapper.py/
test_click_controller.py already follow for their own components.
"""

from __future__ import annotations

from ui.bus import Bus
from ui.events import GameEvent, Observer, RenderEvent


class _RecordingObserver(Observer):
    def __init__(self) -> None:
        self.received: list[GameEvent] = []

    def on_event(self, event: GameEvent) -> None:
        self.received.append(event)


class TestSubscribe:
    def test_a_subscribed_observer_receives_a_published_event(self):
        bus = Bus()
        obs = _RecordingObserver()
        bus.subscribe(obs)

        event = RenderEvent(board_text="hello")
        bus.publish(event)

        assert obs.received == [event]

    def test_publishing_with_no_subscribers_does_not_raise(self):
        bus = Bus()
        bus.publish(RenderEvent(board_text="x"))  # must not raise

    def test_multiple_subscribers_all_receive_the_same_event(self):
        bus = Bus()
        obs_a, obs_b = _RecordingObserver(), _RecordingObserver()
        bus.subscribe(obs_a)
        bus.subscribe(obs_b)

        event = RenderEvent(board_text="shared")
        bus.publish(event)

        assert obs_a.received == [event]
        assert obs_b.received == [event]

    def test_delivery_order_matches_subscription_order(self):
        bus = Bus()
        order: list[str] = []

        class _Tagging(Observer):
            def __init__(self, tag: str) -> None:
                self.tag = tag

            def on_event(self, event: GameEvent) -> None:
                order.append(self.tag)

        bus.subscribe(_Tagging("first"))
        bus.subscribe(_Tagging("second"))
        bus.publish(RenderEvent(board_text="x"))

        assert order == ["first", "second"]

    def test_an_observer_not_subscribed_receives_nothing(self):
        bus = Bus()
        subscribed = _RecordingObserver()
        not_subscribed = _RecordingObserver()
        bus.subscribe(subscribed)

        bus.publish(RenderEvent(board_text="x"))

        assert subscribed.received != []
        assert not_subscribed.received == []


class TestPublish:
    def test_several_published_events_are_all_received_in_order(self):
        bus = Bus()
        obs = _RecordingObserver()
        bus.subscribe(obs)

        events = [RenderEvent("a"), RenderEvent("b"), RenderEvent("c")]
        for e in events:
            bus.publish(e)

        assert obs.received == events
