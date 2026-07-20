"""
Manual verification script for server/server.py.

NOT part of the pytest suite — this is a real network client meant for
a human to run and watch, not something CI drives (see
tests/unit/test_server.py for the in-process, no-real-sockets automated
coverage of the same handler/login logic).

Usage — three separate terminals:

    # Terminal 1: start the real server
    python -m server.server

    # Terminal 2: connect and log in as the first player (becomes White)
    python server/test_client.py Alice

    # Terminal 3: connect and log in as the second player (becomes Black)
    python server/test_client.py Bob

The game doesn't actually start (no tick loop, no board changes) until
BOTH terminals have logged in — see server/server.py's own docstring on
``game_ready``. Each run logs in with the username given on the command
line (or "Player" if omitted), prints the "login_ok"/"login_rejected"
response, then — once logged in — sends two hardcoded (and legal, for
whichever colour it was assigned) pawn moves a second apart, printing
every message the server sends in response, including the other
player's moves. Run a third instance (terminal 4) while the first two
are still logged in to see the "server already has two players"
rejection.
"""

from __future__ import annotations

import asyncio
import json
import sys

from websockets.asyncio.client import connect

SERVER_URL = "ws://localhost:8765"

# Two independent opening pawn moves per colour -- legal regardless of
# what the other player does, so this script never needs to coordinate
# with the other terminal's timing.
WHITE_MOVES = [
    {"type": "move", "from": "e2", "to": "e4"},
    {"type": "move", "from": "d2", "to": "d4"},
]
BLACK_MOVES = [
    {"type": "move", "from": "e7", "to": "e5"},
    {"type": "move", "from": "d7", "to": "d5"},
]


async def _print_incoming(websocket) -> None:
    async for raw in websocket:
        print(f"< {raw}")


async def main(username: str) -> None:
    async with connect(SERVER_URL) as websocket:
        print(f"Connected to {SERVER_URL}")

        login_message = {"type": "login", "username": username}
        print(f"> {json.dumps(login_message)}")
        await websocket.send(json.dumps(login_message))

        first_raw = await websocket.recv()
        print(f"< {first_raw}")
        first_message = json.loads(first_raw)

        if first_message.get("type") == "login_rejected":
            print(f"Login rejected: {first_message.get('reason')}")
            return
        if first_message.get("type") != "login_ok":
            print(f"Unexpected response to login: {first_message}")
            return

        color = first_message.get("color")  # "white" or "black"
        moves = WHITE_MOVES if color == "white" else BLACK_MOVES
        print(f"Logged in as {username!r}, assigned colour: {color!r}")
        print(f"Will send {[m['from'] + '-' + m['to'] for m in moves]} once the game starts "
              f"(waiting for the other player to log in too)")

        print_task = asyncio.create_task(_print_incoming(websocket))

        await asyncio.sleep(1)  # give the other terminal time to connect+log in too
        for move in moves:
            print(f"> {json.dumps(move)}")
            await websocket.send(json.dumps(move))
            await asyncio.sleep(1)

        print("Done sending moves -- still listening for broadcasts for 5s...")
        await asyncio.sleep(5)
        print_task.cancel()


if __name__ == "__main__":
    username = sys.argv[1] if len(sys.argv) > 1 else "Player"
    try:
        asyncio.run(main(username))
    except KeyboardInterrupt:
        sys.exit(0)
