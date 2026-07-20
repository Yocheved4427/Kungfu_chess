"""
Manual verification script for server/server.py.

NOT part of the pytest suite — this is a real network client meant for
a human to run and watch, not something CI drives (see
tests/unit/test_server.py for the in-process, no-real-sockets automated
coverage of the same handler logic).

Usage — three separate terminals:

    # Terminal 1: start the real server
    python -m server.server

    # Terminal 2: connect as the first player (becomes White)
    python server/test_client.py

    # Terminal 3: connect as the second player (becomes Black)
    python server/test_client.py

Each run connects once, prints the "assigned_color" message it gets
back, then sends two hardcoded (and legal, for whichever colour it was
assigned) pawn moves a second apart, printing every message the server
sends in response — including the other player's moves, once both
terminals are connected. Run a fourth instance (terminal 4) while the
first two are still connected to see the "server is full" rejection.
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


async def main() -> None:
    async with connect(SERVER_URL) as websocket:
        print(f"Connected to {SERVER_URL}")

        first_raw = await websocket.recv()
        print(f"< {first_raw}")
        first_message = json.loads(first_raw)

        if first_message.get("type") == "error":
            print(f"Server rejected this connection: {first_message.get('message')}")
            return

        color = first_message.get("color")
        moves = WHITE_MOVES if color == "w" else BLACK_MOVES
        print(f"Assigned colour: {color!r} -- will send {[m['from'] + '-' + m['to'] for m in moves]}")

        print_task = asyncio.create_task(_print_incoming(websocket))

        await asyncio.sleep(1)  # give the other terminal time to connect too
        for move in moves:
            print(f"> {json.dumps(move)}")
            await websocket.send(json.dumps(move))
            await asyncio.sleep(1)

        print("Done sending moves -- still listening for broadcasts for 5s...")
        await asyncio.sleep(5)
        print_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
