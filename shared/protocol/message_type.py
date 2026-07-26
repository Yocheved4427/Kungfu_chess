from __future__ import annotations

from enum import Enum

# ---------------------------------------------------------------------------
# Kung Fu Chess – Protocol Message Type
# ---------------------------------------------------------------------------
# One member per message class in shared.protocol.messages. The string
# VALUE (not the member name) is what actually goes over the wire, in
# every message's serialized "type" field — see
# shared.protocol.protocol.Protocol.
# ---------------------------------------------------------------------------


class MessageType(Enum):
    """Wire-level kind of a shared.protocol message."""
    LOGIN = "login"
    CREATE_ROOM = "create_room"
    JOIN_ROOM = "join_room"
    MOVE_PIECE = "move_piece"
    GAME_STATE_UPDATE = "game_state_update"
    GAME_OVER = "game_over"
    ERROR = "error"
