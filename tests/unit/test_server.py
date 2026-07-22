"""
Unit + integration tests for server/server.py

Scope:
  * TestColorAssignment — GameServer._assign_color()/_release_color()/
    _color_for() in isolation, using plain sentinel objects standing in
    for a ServerConnection (these methods never call anything on the
    object itself, just identity-compare it, so a bare object() is
    enough — no real/fake WebSocket needed for this part).
  * TestLoginFlow — the login handshake through the real handler(),
    using an in-process fake WebSocket (_FakeConnection) instead of a
    real socket: first login -> white, second -> black, third while
    full -> login_rejected + closed, bad usernames -> error, and that
    game_ready/engine/state/board stay unset/None until both players
    have logged in.
  * TestFullMoveRoundTrip — a real end-to-end pass through handler(),
    now including the login step first, then a move.

No real network sockets anywhere in this file — see _FakeConnection.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from core.models import Color, Position
from server.server import MAX_USERNAME_LENGTH, GameServer


# ===========================================================================
# Colour-slot bookkeeping
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

    def test_color_for_an_unassigned_connection_is_none(self):
        server = GameServer()
        assert server._color_for(object()) is None

    def test_color_for_reports_the_assigned_colour(self):
        server = GameServer()
        white_conn = object()
        server._assign_color(white_conn)
        assert server._color_for(white_conn) is Color.WHITE


# ===========================================================================
# In-process fake WebSocket (no real sockets — see this module's header)
# ===========================================================================

class _FakeConnection:
    """A minimal in-process stand-in for websockets' ServerConnection.

    Implements exactly what GameServer.handler()/its helpers use: async
    iteration for incoming messages (backed by an asyncio.Queue so a
    connection can stay "open" awaiting its next message while another
    fake connection's handler runs concurrently), plus send()/close().
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


async def _login(conn: _FakeConnection, username: str) -> None:
    await conn.feed(json.dumps({"type": "login", "username": username}))
    await asyncio.sleep(0)


# ===========================================================================
# Login flow
# ===========================================================================

class TestLoginFlow:
    @pytest.mark.asyncio
    async def test_first_login_gets_white(self):
        server = GameServer()
        conn = _FakeConnection()
        task = asyncio.create_task(server.handler(conn))
        await _login(conn, "alice")

        assert json.loads(conn.sent[-1]) == {"type": "login_ok", "color": "white"}

        await conn.close_incoming()
        await task

    @pytest.mark.asyncio
    async def test_second_login_gets_black(self):
        server = GameServer()
        white_conn, black_conn = _FakeConnection(), _FakeConnection()
        white_task = asyncio.create_task(server.handler(white_conn))
        await _login(white_conn, "alice")
        black_task = asyncio.create_task(server.handler(black_conn))
        await _login(black_conn, "bob")

        assert json.loads(black_conn.sent[-1]) == {"type": "login_ok", "color": "black"}

        await white_conn.close_incoming()
        await black_conn.close_incoming()
        await asyncio.gather(white_task, black_task)

    @pytest.mark.asyncio
    async def test_third_login_is_rejected_and_connection_closed(self):
        server = GameServer()
        white_conn, black_conn, third_conn = _FakeConnection(), _FakeConnection(), _FakeConnection()

        white_task = asyncio.create_task(server.handler(white_conn))
        await _login(white_conn, "alice")
        black_task = asyncio.create_task(server.handler(black_conn))
        await _login(black_conn, "bob")

        third_task = asyncio.create_task(server.handler(third_conn))
        await _login(third_conn, "carol")

        assert json.loads(third_conn.sent[-1]) == {
            "type": "login_rejected",
            "reason": "Server already has two players logged in.",
        }
        assert third_conn.closed is True

        await white_conn.close_incoming()
        await black_conn.close_incoming()
        await asyncio.gather(white_task, black_task, third_task)

    @pytest.mark.asyncio
    async def test_empty_username_is_rejected_with_a_plain_error(self):
        server = GameServer()
        conn = _FakeConnection()
        task = asyncio.create_task(server.handler(conn))
        await _login(conn, "")

        error = json.loads(conn.sent[-1])
        assert error["type"] == "error"
        assert server._color_for(conn) is None  # login did not succeed

        await conn.close_incoming()
        await task

    @pytest.mark.asyncio
    async def test_whitespace_only_username_is_rejected(self):
        server = GameServer()
        conn = _FakeConnection()
        task = asyncio.create_task(server.handler(conn))
        await _login(conn, "   ")

        error = json.loads(conn.sent[-1])
        assert error["type"] == "error"

        await conn.close_incoming()
        await task

    @pytest.mark.asyncio
    async def test_absurdly_long_username_is_rejected(self):
        server = GameServer()
        conn = _FakeConnection()
        task = asyncio.create_task(server.handler(conn))
        await _login(conn, "x" * (MAX_USERNAME_LENGTH + 1))

        error = json.loads(conn.sent[-1])
        assert error["type"] == "error"
        assert server._color_for(conn) is None

        await conn.close_incoming()
        await task

    @pytest.mark.asyncio
    async def test_a_username_at_exactly_the_length_limit_is_accepted(self):
        server = GameServer()
        conn = _FakeConnection()
        task = asyncio.create_task(server.handler(conn))
        await _login(conn, "x" * MAX_USERNAME_LENGTH)

        assert json.loads(conn.sent[-1]) == {"type": "login_ok", "color": "white"}

        await conn.close_incoming()
        await task

    @pytest.mark.asyncio
    async def test_logging_in_twice_on_the_same_connection_is_rejected(self):
        server = GameServer()
        conn = _FakeConnection()
        task = asyncio.create_task(server.handler(conn))
        await _login(conn, "alice")
        await _login(conn, "alice-again")

        error = json.loads(conn.sent[-1])
        assert error["type"] == "error"
        assert server._color_for(conn) is Color.WHITE  # still just the one login

        await conn.close_incoming()
        await task

    @pytest.mark.asyncio
    async def test_a_move_before_logging_in_is_rejected(self):
        server = GameServer()
        conn = _FakeConnection()
        task = asyncio.create_task(server.handler(conn))

        await conn.feed(json.dumps({"type": "move", "from": "e2", "to": "e4"}))
        await asyncio.sleep(0)

        error = json.loads(conn.sent[-1])
        assert error["type"] == "error"

        await conn.close_incoming()
        await task


# ===========================================================================
# game_ready / when the game session actually starts
# ===========================================================================

class TestGameStartsOnlyAfterBothLogins:
    def test_game_ready_is_unset_and_engine_none_right_after_construction(self):
        server = GameServer()
        assert server.game_ready.is_set() is False
        assert server.engine is None
        assert server.state is None
        assert server.board is None

    @pytest.mark.asyncio
    async def test_game_ready_stays_unset_after_only_one_login(self):
        server = GameServer()
        conn = _FakeConnection()
        task = asyncio.create_task(server.handler(conn))
        await _login(conn, "alice")

        assert server.game_ready.is_set() is False
        assert server.engine is None

        await conn.close_incoming()
        await task

    @pytest.mark.asyncio
    async def test_game_ready_is_set_and_engine_built_after_the_second_login(self):
        server = GameServer()
        white_conn, black_conn = _FakeConnection(), _FakeConnection()
        white_task = asyncio.create_task(server.handler(white_conn))
        await _login(white_conn, "alice")
        black_task = asyncio.create_task(server.handler(black_conn))
        await _login(black_conn, "bob")

        assert server.game_ready.is_set() is True
        assert server.engine is not None
        assert server.state is not None
        assert server.board is not None
        assert server.board.get_rows() == server.state.board.get_rows()

        await white_conn.close_incoming()
        await black_conn.close_incoming()
        await asyncio.gather(white_task, black_task)

    @pytest.mark.asyncio
    async def test_run_forever_does_not_tick_until_game_ready_is_set(self):
        """The actual synchronization run_forever() relies on: start it
        as a background task before anyone has logged in, confirm it's
        still just parked on game_ready.wait() (board/engine untouched),
        then log both players in and confirm it proceeds."""
        server = GameServer()
        run_task = asyncio.create_task(server.run_forever())
        await asyncio.sleep(0)

        assert server.game_ready.is_set() is False
        assert server.engine is None  # run_forever hasn't touched it either

        white_conn, black_conn = _FakeConnection(), _FakeConnection()
        white_task = asyncio.create_task(server.handler(white_conn))
        await _login(white_conn, "alice")
        black_task = asyncio.create_task(server.handler(black_conn))
        await _login(black_conn, "bob")

        assert server.game_ready.is_set() is True

        run_task.cancel()
        await white_conn.close_incoming()
        await black_conn.close_incoming()
        await asyncio.gather(white_task, black_task)
        try:
            await run_task
        except asyncio.CancelledError:
            pass


# ===========================================================================
# End-to-end: login, then one full move round-trip through the real handler()
# ===========================================================================

class TestFullMoveRoundTrip:
    @pytest.mark.asyncio
    async def test_a_legal_move_is_queued_lands_on_tick_and_is_broadcast(self):
        server = GameServer()
        white_conn = _FakeConnection()
        black_conn = _FakeConnection()

        white_task = asyncio.create_task(server.handler(white_conn))
        await _login(white_conn, "alice")
        black_task = asyncio.create_task(server.handler(black_conn))
        await _login(black_conn, "bob")

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
        await _login(white_conn, "alice")
        black_task = asyncio.create_task(server.handler(black_conn))
        await _login(black_conn, "bob")

        # White tries to move a BLACK pawn.
        await white_conn.feed(json.dumps({"type": "move", "from": "e7", "to": "e5"}))
        await asyncio.sleep(0)

        error = json.loads(white_conn.sent[-1])
        assert error["type"] == "error"
        assert "e7" in error["message"]
        # Black received nothing beyond its own login_ok message.
        assert len(black_conn.sent) == 1

        await white_conn.close_incoming()
        await black_conn.close_incoming()
        await asyncio.gather(white_task, black_task)

    @pytest.mark.asyncio
    async def test_malformed_json_sends_an_error_and_does_not_crash_the_handler(self):
        server = GameServer()
        conn = _FakeConnection()
        task = asyncio.create_task(server.handler(conn))
        await _login(conn, "alice")

        await conn.feed("not valid json{{{")
        await asyncio.sleep(0)

        error = json.loads(conn.sent[-1])
        assert error["type"] == "error"

        await conn.close_incoming()
        await task  # would raise if the handler had crashed instead of catching it
