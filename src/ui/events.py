from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Kung Fu Chess – UI Events
# ---------------------------------------------------------------------------
# Observer / Subject contracts and immutable event value objects.
#
# Keeping events in their own module:
#   * Breaks the potential engine ↔ io_handler circular-import chain.
#   * Provides a single catalogue to grow without touching emitters or
#     consumers.
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

    Implement this and register with ``GameEngine.add_observer`` to receive
    ``GameEvent`` notifications.
    """

    @abstractmethod
    def on_event(self, event: GameEvent) -> None:
        """Handle an incoming game event."""
