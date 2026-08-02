from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Protocol

from shared.models.board import AbstractBoard
from shared.models.color import Color
from engine.game import GameEngine
from engine.game_state import GameState
from server.game.real_time_arbiter import RealTimeArbiter

# ---------------------------------------------------------------------------
# Kung Fu Chess -- Game Server domain model (services/game_server/domain.py)
# ---------------------------------------------------------------------------
# The "Model" layer: pure domain types only. No Redis, no Kafka, no
# FastAPI, no logging, no printing, nothing that performs I/O -- every
# name in this module can be constructed and reasoned about with zero
# side effects. This is what used to be fused into one 535-line
# services/game_server/main.py; see room_service.py for the layer that
# actually touches Redis/Kafka, and main.py for the FastAPI controller
# that talks to the network.
#
# `Connection` is a Protocol, not fastapi.WebSocket -- the domain model
# doesn't need to know a websocket exists, only that whatever a room's
# player is connected through can send JSON and be closed. Importing
# FastAPI's concrete WebSocket type here would be its own Boundary Lines
# violation (an infrastructure type leaking into the model).
# ---------------------------------------------------------------------------


class Connection(Protocol):
    async def send_json(self, data: dict) -> None: ...
    async def close(self) -> None: ...


class RoomStatus(Enum):
    """A room's lifecycle. Replaces the original implementation's two
    independent `ended: bool` / `paused: bool` flags, which allowed an
    illegal combination (both True at once) the type system had no way
    to rule out. Exactly one of these is ever true for a given room."""
    ACTIVE = auto()
    PAUSED = auto()
    ENDED = auto()


# ---------------------------------------------------------------------------
# Gatekeeper Pattern: one exception family for every domain-level
# rejection this service can produce. Nothing in room_service.py returns
# None on failure or silently no-ops; every caller either gets a
# successful result or a specific, typed exception to handle -- and
# nothing lets a raw stdlib exception (KeyError, ValueError, TypeError)
# escape a business-logic function uncaught.
# ---------------------------------------------------------------------------

class RoomError(Exception):
    """Base class for every exception this service raises deliberately."""


class RoomNotActiveError(RoomError):
    """Raised when an action that requires an ACTIVE room (pause, a
    move) is attempted against a room that's already PAUSED or ENDED --
    replaces the original `_handle_pause`'s silent `return`."""

    def __init__(self, room_id: str, status: RoomStatus) -> None:
        self.room_id = room_id
        self.status = status
        super().__init__(f"room {room_id!r} is not active (status={status.name})")


class InvalidMoveRequestError(RoomError):
    """Raised for a malformed move payload (missing/wrong-typed from/to
    cell fields) -- caught at the controller boundary and turned into a
    clean WS error message instead of an uncaught KeyError/TypeError
    crashing the connection handler."""


class InvalidJoinRequestError(RoomError):
    """Raised for a malformed join request (non-integer user_id/elo
    query params) -- same reasoning as InvalidMoveRequestError."""


class InvalidColorError(RoomError):
    """Raised when a client claims a colour this engine doesn't have.
    The Gatekeeper for what the original implementation let through as
    an unvalidated raw string, silently threaded into player_meta, ELO
    math, and Redis field names."""

    def __init__(self, raw_value: str) -> None:
        self.raw_value = raw_value
        super().__init__(f"{raw_value!r} is not a valid colour (expected 'white' or 'black')")


def color_from_wire(raw: str) -> Color:
    """The single Gatekeeper for turning an untrusted wire-format colour
    string into a real `Color` -- every other place in this service that
    needs a colour must go through this, never `Color(raw)` directly
    (which raises a bare, uncaught ValueError) and never compare against
    the raw string itself."""
    try:
        return Color(raw[0].lower())
    except (IndexError, ValueError):
        raise InvalidColorError(raw) from None


@dataclass
class PlayerMeta:
    """One connected player's identity. Replaces the original
    implementation's untyped `dict` (`{"user_id":..., "elo":...,
    "color":...}`) with `color` as a real `Color`, not a raw string."""
    user_id: int
    elo: int
    color: Color


@dataclass
class RoomGame:
    room_id: str
    board: AbstractBoard
    state: GameState
    engine: GameEngine
    arbiter: RealTimeArbiter
    status: RoomStatus = RoomStatus.ACTIVE
    connections: Dict[str, Connection] = field(default_factory=dict)
    players: Dict[str, PlayerMeta] = field(default_factory=dict)
    pending_events: List[dict] = field(default_factory=list)

    def player_by_color(self, color: Color) -> Optional[PlayerMeta]:
        return next((p for p in self.players.values() if p.color is color), None)


ELO_K_FACTOR = 32


def elo_deltas(white_elo: int, black_elo: int, winner: Optional[Color]) -> tuple[int, int]:
    """Standard ELO delta for both players -- a pure function of ratings
    and outcome, computed fresh at game-end rather than stored anywhere
    mid-game, since the "game ended" Kafka event must carry commutative
    DELTAS, never absolute ratings (decision 11)."""
    expected_white = 1 / (1 + 10 ** ((black_elo - white_elo) / 400))
    expected_black = 1 - expected_white
    score_white = 1.0 if winner is Color.WHITE else 0.0 if winner is Color.BLACK else 0.5
    score_black = 1.0 - score_white
    return (
        round(ELO_K_FACTOR * (score_white - expected_white)),
        round(ELO_K_FACTOR * (score_black - expected_black)),
    )
