"""
Unit + integration tests for server/server.py

Scope:
  * TestColorAssignment — GameServer._assign_color()/_release_color() in
    isolation, using plain sentinel objects standing in for a
    ServerConnection (that method never calls anything on the object
    itself, just identity-compares it, so a bare object() is enough —
    no real/fake WebSocket needed for this part).
  * TestFullMoveRoundTrip — a real end-to-end pass through the actual
    GameServer.handler() coroutine for two concurrent connections, using
    an in-process fake WebSocket (_FakeConnection) instead of a real
    socket, per this task's own "without spinning up real network
    sockets" scope. Drives asyncio directly via pytest-asyncio.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from core.models import Color, Position
from server.server import GameServer


# ===========================================================================
# Colour assignment
# ===========================================================================

class TestColorAssignment:
    def test_first_connection_is_assigned_white(self):
        server = GameServer()
        conn = object()
        assert server._assign_color(conn) is Color.WHITE

    def test_second_connection_is_assigned_black(self):
        server = GameServer()
        server._assign_color(object())
        assert server._assign_color(object()) is Color.BLACK

    def test_third_connection_is_rejected(self):
        server = GameServer()
        server._assign_color(object())
        server._assign_color(object())
        assert server._assign_color(object()) is None

    def test_releasing_white_frees_the_white_slot_for_a_new_connection(self):
        server = GameServer()
        white_conn = object()
        server._assign_color(white_conn)
        server._assign_color(object())  # black

        server._release_color(white_conn)
        new_conn = object()
        assert server._assign_color(new_conn) is Color.WHITE

    def test_releasing_an_unrecognized_connection_is_a_no_op(self):
        server = GameServer()
        server._assign_color(object())  # white
        server._release_color(object())  # some other, never-assigned object
        assert server._assign_color(object()) is Color.BLACK  # white slot still held

    def test_connections_lists_only_currently_assigned_slots(self):
        server = GameServer()
        assert server._connections() == []
        white_conn = object()
        server._assign_color(white_conn)
        assert server._connections() == [white_conn]
        black_conn = object()
        server._assign_color(black_conn)
        assert server._connections() == [white_conn, black_conn]


# ===========================================================================
# End-to-end: one full move round-trip through the real handler()
# ===========================================================================

class _FakeConnection:
    """A minimal in-process stand-in for websockets' ServerConnection.

    Implements exactly what GameServer.handler()/its helpers use: async
    iteration for incoming messages (backed by an asyncio.Queue so a
    connection can stay "open" awaiting its next message while another
    fake connection's handler runs concurrently), plus send()/close().
    No real socket anywhere -- see this module's own header.
    """

    _CLOSE_SENTINEL = object()

    def __init__(self) -> None:
        self._incoming: "asyncio.Queue[object]" = asyncio.Queue()
        self.sent: list[str] = []
        self.closed = False

    async def feed(self, message: str) -> None:
        await self._incoming.put(message)

    async def close_incoming(self) -> None:
        await self._incoming.put(self._CLOSE_SENTINEL)

    def __aiter__(self) -> "_FakeConnection":
        return self

    async def __anext__(self) -> str:
        item = await self._incoming.get()
        if item is self._CLOSE_SENTINEL:
            raise StopAsyncIteration
        return item

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        await self.close_incoming()


class TestFullMoveRoundTrip:
    @pytest.mark.asyncio
    async def test_a_legal_move_is_queued_lands_on_tick_and_is_broadcast(self):
        server = GameServer()
        white_conn = _FakeConnection()
        black_conn = _FakeConnection()

        white_task = asyncio.create_task(server.handler(white_conn))
        await asyncio.sleep(0)  # let white's handler register + get its assigned_color
        black_task = asyncio.create_task(server.handler(black_conn))
        await asyncio.sleep(0)

        assert json.loads(white_conn.sent[0]) == {"type": "assigned_color", "color": "w"}
        assert json.loads(black_conn.sent[0]) == {"type": "assigned_color", "color": "b"}

        # Black moves its own e7 pawn to e5 -- real-time chess has no
        # turn order (see GameEngine.attempt_move's docstring), so black
        # moving first is legal.
        await black_conn.feed(json.dumps({"type": "move", "from": "e7", "to": "e5"}))
        await asyncio.sleep(0)  # let the handler process it (queues a PendingMove)

        # Not applied yet -- attempt_move only queues; advance the clock
        # far enough for the queued move to arrive.
        server.engine.tick(server.state, 1000)

        # The move actually landed on the board.
        assert server.board.get_piece_at(Position(row=3, col=4)) == "bP"  # e5
        assert server.board.get_piece_at(Position(row=1, col=4)) == "."   # e7, now empty

        # And was broadcast as a serialized MoveCompletedEvent via the Bus.
        broadcast_types = []
        while not server._broadcast_queue.empty():
            broadcast_types.append(server._broadcast_queue.get_nowait().get("type"))
        assert "MoveCompletedEvent" in broadcast_types

        await white_conn.close_incoming()
        await black_conn.close_incoming()
        await asyncio.gather(white_task, black_task)

    @pytest.mark.asyncio
    async def test_moving_the_opponents_piece_sends_an_error_to_the_sender_only(self):
        server = GameServer()
        white_conn = _FakeConnection()
        black_conn = _FakeConnection()

        white_task = asyncio.create_task(server.handler(white_conn))
        await asyncio.sleep(0)
        black_task = asyncio.create_task(server.handler(black_conn))
        await asyncio.sleep(0)

        # White tries to move a BLACK pawn.
        await white_conn.feed(json.dumps({"type": "move", "from": "e7", "to": "e5"}))
        await asyncio.sleep(0)

        error = json.loads(white_conn.sent[-1])
        assert error["type"] == "error"
        assert "e7" in error["message"]
        # Black received nothing beyond its own assigned_color message.
        assert len(black_conn.sent) == 1

        await white_conn.close_incoming()
        await black_conn.close_incoming()
        await asyncio.gather(white_task, black_task)

    @pytest.mark.asyncio
    async def test_malformed_json_sends_an_error_and_does_not_crash_the_handler(self):
        server = GameServer()
        conn = _FakeConnection()
        task = asyncio.create_task(server.handler(conn))
        await asyncio.sleep(0)

        await conn.feed("not valid json{{{")
        await asyncio.sleep(0)

        error = json.loads(conn.sent[-1])
        assert error["type"] == "error"

        await conn.close_incoming()
        await task  # would raise if the handler had crashed instead of catching it

    @pytest.mark.asyncio
    async def test_third_connection_receives_error_and_is_closed(self):
        server = GameServer()
        white_conn, black_conn, third_conn = _FakeConnection(), _FakeConnection(), _FakeConnection()

        white_task = asyncio.create_task(server.handler(white_conn))
        await asyncio.sleep(0)
        black_task = asyncio.create_task(server.handler(black_conn))
        await asyncio.sleep(0)

        await server.handler(third_conn)  # both slots taken -- returns immediately

        assert json.loads(third_conn.sent[-1]) == {
            "type": "error",
            "message": "Server already has two players connected.",
        }
        assert third_conn.closed is True

        await white_conn.close_incoming()
        await black_conn.close_incoming()
        await asyncio.gather(white_task, black_task)
