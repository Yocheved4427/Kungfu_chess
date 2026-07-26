from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields
from typing import ClassVar, Dict, Optional, Tuple

from shared.models.cell import Cell
from shared.protocol.message_type import MessageType

# ---------------------------------------------------------------------------
# Kung Fu Chess – Protocol Messages
# ---------------------------------------------------------------------------
# One frozen dataclass per shared.protocol.message_type.MessageType
# member. Every message is convertible to/from a plain JSON-able dict
# via to_dict()/from_dict() — shared.protocol.protocol.Protocol builds
# on exactly these two methods, it doesn't know each message's fields
# itself.
#
# This is NOT the wire format server/server.py and network_client.py
# speak to each other (see shared/protocol/protocol.py's own docstring
# for the full comparison) — it's server/network/server.py's, the
# room/matchmaking-capable socket server that actually implements
# CreateRoomMessage/JoinRoomMessage's "rooms" concept.
# ---------------------------------------------------------------------------


def _cell_to_dict(cell: Cell) -> dict:
    return {"row": cell.row, "col": cell.col}


def _cell_from_dict(data: dict) -> Cell:
    return Cell(row=data["row"], col=data["col"])


class Message(ABC):
    """Base class for every shared.protocol message.

    Concrete subclasses are frozen dataclasses that set their own
    ``MESSAGE_TYPE`` and, only when a field needs non-trivial encoding
    (e.g. a ``Cell``), override ``to_dict``/``from_dict``.
    """

    MESSAGE_TYPE: ClassVar[MessageType]

    def to_dict(self) -> dict:
        """Default encoding: "type" plus every dataclass field
        untouched. Only valid for messages whose fields are all
        already JSON-primitive (str/int/bool/None/list) — messages
        with a ``Cell`` field (e.g. ``MovePieceMessage``) override
        this instead.
        """
        return {
            "type": self.MESSAGE_TYPE.value,
            **{f.name: getattr(self, f.name) for f in fields(self)},
        }

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict) -> "Message":
        """Build this message from its own ``to_dict()`` output (an
        extra "type" key, if present, is ignored — the caller is
        expected to have already used it to pick this class)."""


@dataclass(frozen=True)
class LoginMessage(Message):
    """Client -> server: log in with a username/password against the
    server's user database (see server.services.auth_service.
    AuthService.login — unrelated to server/server.py's own,
    separate, password-less username-only login).

    ``password`` was added after this class's original,
    server/server.py-shaped design (username only, no accounts) — this
    message now targets a real, database-backed account instead.
    """
    username: str
    password: str

    MESSAGE_TYPE: ClassVar[MessageType] = MessageType.LOGIN

    @classmethod
    def from_dict(cls, data: dict) -> "LoginMessage":
        return cls(username=data["username"], password=data["password"])


@dataclass(frozen=True)
class RegisterMessage(Message):
    """Client -> server: create a new account with a username/password
    (see server.services.auth_service.AuthService.register)."""
    username: str
    password: str

    MESSAGE_TYPE: ClassVar[MessageType] = MessageType.REGISTER

    @classmethod
    def from_dict(cls, data: dict) -> "RegisterMessage":
        return cls(username=data["username"], password=data["password"])


@dataclass(frozen=True)
class CreateRoomMessage(Message):
    """Client -> server: create a new room to play in."""
    room_name: str

    MESSAGE_TYPE: ClassVar[MessageType] = MessageType.CREATE_ROOM

    @classmethod
    def from_dict(cls, data: dict) -> "CreateRoomMessage":
        return cls(room_name=data["room_name"])


@dataclass(frozen=True)
class JoinRoomMessage(Message):
    """Client -> server: join an existing room by id."""
    room_id: str

    MESSAGE_TYPE: ClassVar[MessageType] = MessageType.JOIN_ROOM

    @classmethod
    def from_dict(cls, data: dict) -> "JoinRoomMessage":
        return cls(room_id=data["room_id"])


@dataclass(frozen=True)
class QueueForMatchMessage(Message):
    """Client -> server: join the ELO-based matchmaking queue instead
    of creating/joining a room directly (see
    server.services.matchmaking_service.MatchmakingService). No fields
    of its own — the server already knows the connection's username
    and ELO rating from its login.
    """

    MESSAGE_TYPE: ClassVar[MessageType] = MessageType.QUEUE_FOR_MATCH

    @classmethod
    def from_dict(cls, data: dict) -> "QueueForMatchMessage":
        return cls()


@dataclass(frozen=True)
class MovePieceMessage(Message):
    """Client -> server: attempt to move one piece."""
    from_cell: Cell
    to_cell: Cell
    piece_id: str

    MESSAGE_TYPE: ClassVar[MessageType] = MessageType.MOVE_PIECE

    def to_dict(self) -> dict:
        return {
            "type": self.MESSAGE_TYPE.value,
            "from_cell": _cell_to_dict(self.from_cell),
            "to_cell": _cell_to_dict(self.to_cell),
            "piece_id": self.piece_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MovePieceMessage":
        return cls(
            from_cell=_cell_from_dict(data["from_cell"]),
            to_cell=_cell_from_dict(data["to_cell"]),
            piece_id=data["piece_id"],
        )


@dataclass(frozen=True)
class GameStateUpdateMessage(Message):
    """Server -> client: full board resync."""
    board: Tuple[str, ...]
    current_time: int

    MESSAGE_TYPE: ClassVar[MessageType] = MessageType.GAME_STATE_UPDATE

    def to_dict(self) -> dict:
        return {
            "type": self.MESSAGE_TYPE.value,
            "board": list(self.board),
            "current_time": self.current_time,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameStateUpdateMessage":
        return cls(board=tuple(data["board"]), current_time=data["current_time"])


@dataclass(frozen=True)
class GameOverMessage(Message):
    """Server -> client: the game has ended."""
    winner: Optional[str]  # Color.value ("w"/"b"), or None

    MESSAGE_TYPE: ClassVar[MessageType] = MessageType.GAME_OVER

    @classmethod
    def from_dict(cls, data: dict) -> "GameOverMessage":
        return cls(winner=data["winner"])


@dataclass(frozen=True)
class ErrorMessage(Message):
    """Server -> client: something the client sent was rejected."""
    message: str

    MESSAGE_TYPE: ClassVar[MessageType] = MessageType.ERROR

    @classmethod
    def from_dict(cls, data: dict) -> "ErrorMessage":
        return cls(message=data["message"])


@dataclass(frozen=True)
class AckMessage(Message):
    """Server -> client: a generic success acknowledgment for a
    request that has no dedicated response message of its own (login,
    register, create_room, join_room) — one message type covers all
    four rather than a dedicated class each. ``request_type`` names
    which request this acks (e.g. ``"login"``, ``"create_room"``);
    ``detail`` carries whatever small amount of request-specific data
    the client needs next (e.g. ``{"color": "white"}`` for a login ack,
    ``{"room_id": "a1b2c3d4"}`` for a create_room ack) — a plain
    ``{str: str}`` mapping so this stays one message type instead of
    several.
    """
    request_type: str
    detail: Dict[str, str] = field(default_factory=dict)

    MESSAGE_TYPE: ClassVar[MessageType] = MessageType.ACK

    @classmethod
    def from_dict(cls, data: dict) -> "AckMessage":
        return cls(request_type=data["request_type"], detail=data.get("detail", {}))
