from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Kung Fu Chess – Room Service
# ---------------------------------------------------------------------------
# Room creation, joining, and lifecycle management for two-player
# lobbies — there was no "room" concept anywhere in this codebase
# before this (server/server.py's own module docstring calls rooms out
# explicitly as "a later task, not this one"; shared/protocol/
# messages.py's CreateRoomMessage/JoinRoomMessage were built standalone,
# ahead of any server that actually implements rooms — this is that
# implementation, used by server/network/server.py).
#
# Knows nothing about sockets, ELO, or chess itself — pure in-memory
# lobby bookkeeping (usernames as plain strings, no user_id/database
# lookups here). Not thread-safe on its own: a caller mutating it from
# multiple threads (server/network/server.py runs one thread per
# connection) must serialize access itself — see that module's own
# locking.
# ---------------------------------------------------------------------------


class RoomStatus(Enum):
    """A room's lifecycle state."""
    WAITING_FOR_PLAYERS = auto()  # 0 or 1 players joined
    READY = auto()                # exactly MAX_PLAYERS joined; game not yet started
    IN_PROGRESS = auto()          # game started (see RoomService.start)
    CLOSED = auto()               # emptied out; no longer joinable or listed


@dataclass
class Room:
    """One two-player lobby.

    ``players`` is join order, capped at ``RoomService.MAX_PLAYERS`` —
    ``players[0]`` is conventionally White, ``players[1]`` Black,
    mirroring server/server.py's own first-login-is-White convention.
    """
    room_id: str
    room_name: str
    players: List[str] = field(default_factory=list)
    status: RoomStatus = RoomStatus.WAITING_FOR_PLAYERS


class JoinOutcome(Enum):
    """Outcome of ``RoomService.join_room`` — never a bare bool, same
    idiom as this codebase's other legality/result types (``MoveResult``,
    ``MoveLegality``, ``AuthOutcome``)."""
    OK = auto()
    ROOM_NOT_FOUND = auto()
    ROOM_FULL = auto()
    ALREADY_IN_ROOM = auto()

    @property
    def is_ok(self) -> bool:
        return self is JoinOutcome.OK


class RoomService:
    """In-memory registry of every open ``Room``."""

    MAX_PLAYERS = 2

    def __init__(self) -> None:
        self._rooms: Dict[str, Room] = {}

    def create_room(self, room_name: str) -> Room:
        """Create a new, empty, joinable room and return it. *room_id*
        is a short random hex id (``uuid.uuid4().hex[:8]``) — collision
        odds are negligible for any realistic number of concurrent
        rooms, and a caller never has to supply one itself.
        """
        room_id = uuid.uuid4().hex[:8]
        room = Room(room_id=room_id, room_name=room_name)
        self._rooms[room_id] = room
        return room

    def join_room(self, room_id: str, username: str) -> JoinOutcome:
        """Add *username* to *room_id*'s player list.

        Transitions the room to ``RoomStatus.READY`` the instant it
        reaches ``MAX_PLAYERS`` — the caller (server/network/server.py)
        is the one that actually starts a game once it sees that; this
        method only updates lobby bookkeeping.
        """
        room = self._rooms.get(room_id)
        if room is None:
            return JoinOutcome.ROOM_NOT_FOUND
        if username in room.players:
            return JoinOutcome.ALREADY_IN_ROOM
        if len(room.players) >= self.MAX_PLAYERS:
            return JoinOutcome.ROOM_FULL

        room.players.append(username)
        if len(room.players) == self.MAX_PLAYERS:
            room.status = RoomStatus.READY
        return JoinOutcome.OK

    def leave_room(self, room_id: str, username: str) -> None:
        """Remove *username* from *room_id*, if present.

        An emptied room closes outright (``RoomStatus.CLOSED``) rather
        than lingering forever; a room that still has one player left
        reverts to ``WAITING_FOR_PLAYERS`` — even if it was
        ``IN_PROGRESS``; tearing down that room's actual game is the
        caller's job (this method only updates lobby bookkeeping). A
        missing room, or a username not in it, is a silent no-op.
        """
        room = self._rooms.get(room_id)
        if room is None or username not in room.players:
            return
        room.players.remove(username)
        room.status = (
            RoomStatus.CLOSED if not room.players else RoomStatus.WAITING_FOR_PLAYERS
        )

    def start(self, room_id: str) -> None:
        """Mark *room_id* as ``IN_PROGRESS`` — called once its game has
        actually been constructed. A no-op if the room doesn't exist.
        """
        room = self._rooms.get(room_id)
        if room is not None:
            room.status = RoomStatus.IN_PROGRESS

    def get_room(self, room_id: str) -> Optional[Room]:
        """Fetch a room by id, or ``None`` if it doesn't exist (or has
        since closed and been forgotten — see ``leave_room``)."""
        return self._rooms.get(room_id)

    def list_rooms(self) -> List[Room]:
        """Every open (not ``CLOSED``) room, for a lobby listing."""
        return [room for room in self._rooms.values() if room.status is not RoomStatus.CLOSED]
