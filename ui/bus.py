from __future__ import annotations

from typing import List

from ui.events import GameEvent, Observer

# ---------------------------------------------------------------------------
# Kung Fu Chess – Event Bus
# ---------------------------------------------------------------------------
# Formalizes the pub/sub mechanism GameEngine already implemented inline
# (a List[Observer] plus add/notify) as its own named, independently
# testable class. GameEngine now delegates add_observer()/_notify() to a
# Bus instance instead of managing the list itself -- its own public API
# is unchanged (see that class's own comments), so every existing
# GameEngine test keeps passing without modification.
#
# Why formalize this now, with no networking yet: a future WebSocket
# server will want a Bus of its own to fan events out to connected
# clients (subscribe = one client's send-to-socket callback, publish =
# whatever GameEngine already calls _notify with) -- giving the concept
# a real, reusable class today means that server can depend on Bus
# directly instead of reaching into GameEngine's internals.
# ---------------------------------------------------------------------------


class Bus:
    """Minimal pub/sub event bus: observers subscribe, publishers publish.

    Delivery is synchronous and in subscription order -- identical to
    the inline list-based mechanism this replaces. No error handling,
    ordering guarantees, or unsubscribe yet: exactly the same contract
    GameEngine's observers already relied on, just under its own name.
    """

    def __init__(self) -> None:
        self._observers: List[Observer] = []

    def subscribe(self, observer: Observer) -> None:
        """Register *observer* to receive every future ``publish()``."""
        self._observers.append(observer)

    def publish(self, event: GameEvent) -> None:
        """Deliver *event* to every subscribed observer, in subscription order."""
        for observer in self._observers:
            observer.on_event(event)
