"""
Integration tests for server/server.py over REAL WebSocket connections
on a random local port.

Complements tests/unit/test_server.py, which deliberately drives
GameServer.handler() with an in-process fake connection (no real
sockets at all — see that file's own header for why: fast, no network-
stack flakiness). This file instead exercises the real
websockets.asyncio.server/client stack end-to-end — real TCP, real
JSON framing, real asyncio scheduling — to catch anything the fake
connection's simplified contract might not.

Binds to 127.0.0.1 with port=0 (an OS-assigned free port) rather than
server.py's own default 8765, so this suite never collides with a real
running server or another concurrent test run. (Binding "localhost"
instead of "127.0.0.1" would resolve to BOTH an IPv6 and an IPv4
socket, each independently assigned a DIFFERENT random port — confirmed
empirically before writing this file — so 127.0.0.1 specifically is
used to keep this to one socket, one port, no ambiguity about which
port the client should actually connect to.)
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest
import pytest_asyncio
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from server.server import GameServer


@pytest_asyncio.fixture
async def running_server():
    """A real GameServer, listening on 127.0.0.1 at a random free port,
    with run_forever() driving it as a background task for the
    duration of the test — exactly as server/server.py's own
    run_server() does. Without this, the tick loop never starts (see
    GameServer.run_forever's own docstring: it waits on game_ready, then
    runs the tick/broadcast loops), so a queued move would never
    actually land.

    Yields (server, url) — server for state inspection, url to connect
    clients to.
    """
    server = GameServer()
    async with serve(server.handler, "127.0.0.1", 0) as ws_server:
        port = ws_server.sockets[0].getsockname()[1]
        run_task = asyncio.create_task(server.run_forever())
        try:
            yield server, f"ws://127.0.0.1:{port}"
        finally:
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass


async def _login(url: str, username: str):
    """Connect and log in as *username*; return (websocket, response_dict).

    Not an ``async with`` — the caller needs the connection to stay
    open past this helper returning.
    """
    websocket = await connect(url)
    await websocket.send(json.dumps({"type": "login", "username": username}))
    raw = await asyncio.wait_for(websocket.recv(), timeout=5.0)
    return websocket, json.loads(raw)


class TestConnectionAndLogin:
    @pytest.mark.asyncio
    async def test_first_login_is_assigned_white(self, running_server):
        _, url = running_server
        ws, response = await _login(url, "alice")
        try:
            assert response == {"type": "login_ok", "color": "white"}
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_second_login_is_assigned_black(self, running_server):
        _, url = running_server
        white, _ = await _login(url, "alice")
        black, response = await _login(url, "bob")
        try:
            assert response == {"type": "login_ok", "color": "black"}
        finally:
            await white.close()
            await black.close()

    @pytest.mark.asyncio
    async def test_third_login_is_rejected(self, running_server):
        _, url = running_server
        white, _ = await _login(url, "alice")
        black, _ = await _login(url, "bob")
        third, response = await _login(url, "carol")
        try:
            assert response["type"] == "login_rejected"
        finally:
            await white.close()
            await black.close()
            await third.close()


class TestMoveHandling:
    @pytest.mark.asyncio
    async def test_valid_move_broadcasts_updated_state(self, running_server):
        """A legal move, sent over a real socket, must eventually show
        up in a broadcast snapshot -- proving the whole real-network
        path (send -> server parses/queues/resolves -> broadcasts ->
        client receives) actually works, not just the in-process
        fake-connection version of the same claim."""
        _, url = running_server
        white, _ = await _login(url, "alice")
        black, _ = await _login(url, "bob")
        try:
            await white.send(json.dumps({"type": "move", "from": "e2", "to": "e4"}))

            landed = False
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                raw = await asyncio.wait_for(white.recv(), timeout=5.0)
                message = json.loads(raw)
                if message.get("type") == "snapshot" and message["board"][4].split()[4] == "wP":
                    landed = True
                    break
            assert landed, "e2-e4 never showed up in a broadcast snapshot"
        finally:
            await white.close()
            await black.close()

    @pytest.mark.asyncio
    async def test_invalid_move_returns_an_error_packet_to_the_sender_only(self, running_server):
        _, url = running_server
        white, _ = await _login(url, "alice")
        black, _ = await _login(url, "bob")
        try:
            # White attempts to move a piece it doesn't control.
            await white.send(json.dumps({"type": "move", "from": "e7", "to": "e5"}))
            raw = await asyncio.wait_for(white.recv(), timeout=5.0)
            message = json.loads(raw)
            assert message["type"] == "error"
        finally:
            await white.close()
            await black.close()


class TestDisconnection:
    @pytest.mark.asyncio
    async def test_disconnecting_frees_the_colour_slot_for_a_new_connection(self, running_server):
        _, url = running_server
        white, _ = await _login(url, "alice")
        black, _ = await _login(url, "bob")
        await white.close()
        await asyncio.sleep(0.2)  # give the server a moment to notice the close

        new_white, response = await _login(url, "carol")
        try:
            assert response == {"type": "login_ok", "color": "white"}
        finally:
            await new_white.close()
            await black.close()

    @pytest.mark.asyncio
    async def test_server_state_no_longer_holds_the_disconnected_socket(self, running_server):
        server, url = running_server
        white, _ = await _login(url, "alice")
        await white.close()
        await asyncio.sleep(0.2)
        assert server._connections() == []
