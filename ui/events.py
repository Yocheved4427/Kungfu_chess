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


@dataclass(frozen=True)
class TimeAdvancedEvent(GameEvent):
    """Fired after the game clock advances (i.e. after every ``tick`` call)."""
    current_time: int


@dataclass(frozen=True)
class MoveCompletedEvent(GameEvent):
    """Fired once for each pending move that executes during a ``tick``."""
    piece: str
    from_pos: object   # Position – typed as object to avoid a cross-layer import
    to_pos: object     # Position
    arrival_time: int


class Observer(ABC):
    """Observer interface.

    Implement this and register with ``GameEngine.add_observer`` to receive
    ``GameEvent`` notifications.
    """

    @abstractmethod
    def on_event(self, event: GameEvent) -> None:
        """Handle an incoming game event."""
