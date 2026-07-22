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


def _position_dict(pos: object) -> dict:
    """{"row": int, "col": int} for any Position-shaped object.

    Duck-typed (reads ``.row``/``.col`` off whatever was actually
    passed) rather than importing ``core.models.Position`` — every
    event field that holds a Position is itself typed as ``object`` for
    exactly this reason (see each field's own comment below), so
    serialization can't need the import either.
    """
    return {"row": pos.row, "col": pos.col}


@dataclass(frozen=True)
class GameEvent:
    """Immutable marker base class for all game events."""

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict representation of this event.

        Every subclass overrides this to layer its own fields on top;
        the "type" key is always the concrete subclass's own name (via
        ``type(self).__name__``, evaluated on the real instance even
        when called through this base implementation) so a future
        receiver — e.g. a WebSocket client with no Python type
        information at all — can dispatch purely on that string.
        """
        return {"type": type(self).__name__}


@dataclass(frozen=True)
class RenderEvent(GameEvent):
    """Fired when the current board state should be rendered/displayed."""
    board_text: str

    def to_dict(self) -> dict:
        return {**super().to_dict(), "board_text": self.board_text}


@dataclass(frozen=True)
class TimeAdvancedEvent(GameEvent):
    """Fired after the game clock advances (i.e. after every ``tick`` call)."""
    current_time: int

    def to_dict(self) -> dict:
        return {**super().to_dict(), "current_time": self.current_time}


@dataclass(frozen=True)
class MoveCompletedEvent(GameEvent):
    """Fired once for each pending move that executes during a ``tick``."""
    piece: str
    from_pos: object   # Position – typed as object to avoid a cross-layer import
    to_pos: object     # Position
    arrival_time: int

    def to_dict(self) -> dict:
        return {
            **super().to_dict(),
            "piece": self.piece,
            "from_pos": _position_dict(self.from_pos),
            "to_pos": _position_dict(self.to_pos),
            "arrival_time": self.arrival_time,
        }


@dataclass(frozen=True)
class GameOverEvent(GameEvent):
    """Fired exactly once, the moment the game ends (see ``GameOverRule``)."""
    winner: object      # Color | None – typed as object to avoid a cross-layer import

    def to_dict(self) -> dict:
        return {
            **super().to_dict(),
            "winner": self.winner.value if self.winner is not None else None,
        }


@dataclass(frozen=True)
class JumpLandedEvent(GameEvent):
    """Fired when a jump's window elapses with no enemy arrival — the
    piece grounds again, unchanged, on the same cell it jumped from."""
    piece: str
    pos: object        # Position – typed as object to avoid a cross-layer import
    land_time: int

    def to_dict(self) -> dict:
        return {
            **super().to_dict(),
            "piece": self.piece,
            "pos": _position_dict(self.pos),
            "land_time": self.land_time,
        }


@dataclass(frozen=True)
class AirborneCaptureEvent(GameEvent):
    """Fired when an airborne piece captures an enemy that arrived at its
    cell during the jump window. The defender never moves; the attacker
    is removed outright — it never reaches ``pos``."""
    defender: str
    pos: object        # Position – the airborne piece's cell
    attacker: str

    def to_dict(self) -> dict:
        return {
            **super().to_dict(),
            "defender": self.defender,
            "pos": _position_dict(self.pos),
            "attacker": self.attacker,
        }


class Observer(ABC):
    """Observer interface.

    Implement this and register with ``GameEngine.add_observer`` to receive
    ``GameEvent`` notifications.
    """

    @abstractmethod
    def on_event(self, event: GameEvent) -> None:
        """Handle an incoming game event."""
