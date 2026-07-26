from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, fields
from typing import ClassVar, Optional, Tuple

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
# Standalone, new addition: this is NOT the wire format
# server/server.py and network_client.py already speak to each other
# (see shared/protocol/protocol.py's own docstring for the full
# comparison) — there is no "rooms" concept anywhere else in this
# codebase yet, so CreateRoomMessage/JoinRoomMessage don't correspond
# to anything a server currently implements.
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
    """Client -> server: log in with a username."""
    username: str

    MESSAGE_TYPE: ClassVar[MessageType] = MessageType.LOGIN

    @classmethod
    def from_dict(cls, data: dict) -> "LoginMessage":
        return cls(username=data["username"])


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
