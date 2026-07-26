from __future__ import annotations

import json
import socket
from typing import Dict, Type

from shared.protocol.message_type import MessageType
from shared.protocol.messages import (
    AckMessage,
    CreateRoomMessage,
    ErrorMessage,
    GameOverMessage,
    GameStateUpdateMessage,
    JoinRoomMessage,
    LoginMessage,
    Message,
    MovePieceMessage,
    QueueForMatchMessage,
    RegisterMessage,
)

# ---------------------------------------------------------------------------
# Kung Fu Chess – Socket Protocol
# ---------------------------------------------------------------------------
# Length-prefix framing over a raw, blocking TCP socket: a 4-byte
# big-endian header giving the UTF-8 JSON payload's byte length,
# followed by the payload itself. Framing is needed here because a raw
# socket is just a byte stream with no message boundaries of its own.
#
# Used by server/network/server.py (the room/matchmaking-capable
# socket server) — NOT by server/server.py or network_client.py, which
# predate rooms entirely and run their own, different multiplayer
# pipeline over the `websockets` library (which frames one message per
# call on its own, so none of this is needed there), speaking their
# own ad hoc JSON shapes (`{"type": "login", "username": ...}`,
# `{"type": "move", "from": "e2", "to": "e4"}`, `{"type": "snapshot",
# "board": [...], ...}` — see server/server.py's own module docstring).
# Both pipelines coexist deliberately (see server/network/server.py's
# own module docstring for why) rather than one replacing the other.
# ---------------------------------------------------------------------------

_HEADER_LENGTH = 4  # bytes; big-endian unsigned length of the JSON payload

_MESSAGE_CLASSES: Dict[MessageType, Type[Message]] = {
    MessageType.LOGIN: LoginMessage,
    MessageType.REGISTER: RegisterMessage,
    MessageType.CREATE_ROOM: CreateRoomMessage,
    MessageType.JOIN_ROOM: JoinRoomMessage,
    MessageType.QUEUE_FOR_MATCH: QueueForMatchMessage,
    MessageType.MOVE_PIECE: MovePieceMessage,
    MessageType.GAME_STATE_UPDATE: GameStateUpdateMessage,
    MessageType.GAME_OVER: GameOverMessage,
    MessageType.ERROR: ErrorMessage,
    MessageType.ACK: AckMessage,
}


class ProtocolError(ValueError):
    """Raised for any malformed input Protocol is asked to decode, or
    a connection that closes mid-message."""


class Protocol:
    """Stateless ``Message`` <-> JSON <-> framed-bytes conversion.

    Every method is a ``@staticmethod`` — ``Protocol`` holds no
    per-connection state, so the class itself is used directly; there
    is nothing to construct.
    """

    @staticmethod
    def encode(message: Message) -> bytes:
        """Serialize *message* to a UTF-8 JSON payload — no length
        prefix. See ``pack_for_socket``/``send`` for the framed form
        actually written to a raw socket.
        """
        return json.dumps(message.to_dict()).encode("utf-8")

    @staticmethod
    def decode(data: bytes) -> Message:
        """Inverse of ``encode``: parse a UTF-8 JSON payload back into
        the concrete ``Message`` subclass its "type" field names.

        Raises ``ProtocolError`` iff *data* isn't valid UTF-8/JSON,
        isn't a JSON object, has a missing/unrecognized "type", or is
        missing a field its message type requires.
        """
        try:
            parsed = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProtocolError(f"Invalid JSON payload: {exc}") from exc

        if not isinstance(parsed, dict):
            raise ProtocolError(f"Expected a JSON object, got {type(parsed).__name__}")

        raw_type = parsed.get("type")
        try:
            message_type = MessageType(raw_type)
        except ValueError as exc:
            raise ProtocolError(f"Unknown message type {raw_type!r}") from exc

        message_cls = _MESSAGE_CLASSES[message_type]
        try:
            return message_cls.from_dict(parsed)
        except KeyError as exc:
            raise ProtocolError(
                f"{message_type.value} message missing required field {exc}"
            ) from exc

    @staticmethod
    def pack_for_socket(message: Message) -> bytes:
        """Frame *message* for a raw socket: 4-byte big-endian payload
        length, followed by the JSON payload itself."""
        payload = Protocol.encode(message)
        return len(payload).to_bytes(_HEADER_LENGTH, "big") + payload

    @staticmethod
    def send(sock: socket.socket, message: Message) -> None:
        """Frame and write *message* to *sock* in full (``sendall``
        loops internally on short writes)."""
        sock.sendall(Protocol.pack_for_socket(message))

    @staticmethod
    def _recv_exact(sock: socket.socket, num_bytes: int) -> bytes:
        """Block until exactly *num_bytes* have arrived on *sock*.

        Raises ``ProtocolError`` if the peer closes the connection
        first — a raw socket's ``recv`` returning ``b""`` mid-message
        means exactly that, since a stream socket has no other way to
        signal it.
        """
        chunks = []
        remaining = num_bytes
        while remaining > 0:
            chunk = sock.recv(remaining)
            if not chunk:
                raise ProtocolError(
                    f"Connection closed after {num_bytes - remaining}/{num_bytes} bytes"
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    @staticmethod
    def receive(sock: socket.socket) -> Message:
        """Block until one full framed message has arrived on *sock*,
        then decode it — the inverse of ``send``."""
        header = Protocol._recv_exact(sock, _HEADER_LENGTH)
        payload_length = int.from_bytes(header, "big")
        payload = Protocol._recv_exact(sock, payload_length)
        return Protocol.decode(payload)
