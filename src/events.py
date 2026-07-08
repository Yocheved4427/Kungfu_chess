from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Kung Fu Chess – Game Events (Iteration 3)
# ---------------------------------------------------------------------------
# Observer / Subject interfaces and immutable event value objects.
#
# Why here?
#   Keeping events in their own module breaks a potential circular-import
#   chain (engine ↔ io_handler) and gives a single place to grow the event
#   catalogue without touching any class that emits or consumes events.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GameEvent:
    """Immutable marker base class for all game events."""


@dataclass(frozen=True)
class RenderEvent(GameEvent):
    """Fired when the current board state should be rendered/displayed."""

    board_text: str


class Observer(ABC):
    """Observer interface.

    Implement this and register with a ``GameEngine`` via ``add_observer``
    to receive ``GameEvent`` notifications.
    """

    @abstractmethod
    def on_event(self, event: GameEvent) -> None:
        """Handle an incoming game event."""
