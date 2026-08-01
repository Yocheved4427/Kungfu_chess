from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Optional, Union

import nats
from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg

from shared.logger_config import setup_logging
from shared.models.cell import Cell

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kung Fu Chess -- NATS Client communication module (client/nats_client.py)
# ---------------------------------------------------------------------------
# The player-side counterpart to server/nats/game_server.py: publishes
# action messages (join/move) to `game.room.<room_id>.events` and
# delivers every message the server publishes on
# `game.room.<room_id>.state` to a caller-supplied handler.
#
# Pure transport, same separation of concerns as ui/network_client.py
# and client/network/client.py: this module decides nothing about
# legality or rendering, and holds no board state of its own -- a
# caller (a render loop, a test script) owns interpreting the "state"
# payloads this delivers. Unlike ui/network_client.py (which bridges
# the `websockets` library into a background thread + queue.Queue for a
# synchronous OpenCV render loop), nats-py is asyncio-native throughout,
# so no such bridging is needed here -- a synchronous caller wanting the
# same bridge pattern can wrap NatsGameClient the same way
# ui/network_client.py wraps its own websocket connection.
# ---------------------------------------------------------------------------

DEFAULT_NATS_URL = "nats://localhost:4222"

StateHandler = Callable[[dict], Union[Awaitable[None], None]]


def events_subject(room_id: str) -> str:
    return f"game.room.{room_id}.events"


def state_subject(room_id: str) -> str:
    return f"game.room.{room_id}.state"


class NatsGameClient:
    """One room's NATS pub/sub connection, from a single player's side."""

    def __init__(self, room_id: str, on_state: StateHandler, nats_url: str = DEFAULT_NATS_URL) -> None:
        self._room_id = room_id
        self._on_state = on_state
        self._nats_url = nats_url
        self._nc: Optional[NatsClient] = None

    async def connect(self) -> None:
        self._nc = await nats.connect(self._nats_url)
        await self._nc.subscribe(state_subject(self._room_id), cb=self._on_state_message)
        logger.info("Connected to %s, subscribed to room %r state", self._nats_url, self._room_id)

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.drain()

    async def join(self, username: str) -> None:
        await self._publish_event({"type": "join", "player": username})

    async def send_move(self, username: str, from_cell: Cell, to_cell: Cell) -> None:
        await self._publish_event({
            "type": "move",
            "player": username,
            "from": {"row": from_cell.row, "col": from_cell.col},
            "to": {"row": to_cell.row, "col": to_cell.col},
        })

    async def _publish_event(self, payload: dict) -> None:
        await self._nc.publish(events_subject(self._room_id), json.dumps(payload).encode("utf-8"))

    async def _on_state_message(self, msg: Msg) -> None:
        try:
            payload: dict[str, Any] = json.loads(msg.data)
        except json.JSONDecodeError:
            logger.warning("Malformed state message on %s: %r", msg.subject, msg.data)
            return
        result = self._on_state(payload)
        if asyncio.iscoroutine(result):
            await result


async def _demo() -> None:
    """Standalone smoke-test client: joins a room and prints every state
    message it receives -- `python -m client.nats_client <room_id> <username>`.
    Run it twice (two usernames, same room_id) against a running
    server/nats/game_server.py to see a real room start and tick.
    """
    parser = argparse.ArgumentParser(description="Kung Fu Chess NATS client demo")
    parser.add_argument("room_id")
    parser.add_argument("username")
    parser.add_argument("--nats-url", default=DEFAULT_NATS_URL, help=f"Default: {DEFAULT_NATS_URL}")
    args = parser.parse_args()

    setup_logging()

    def on_state(payload: dict) -> None:
        print(payload)

    client = NatsGameClient(args.room_id, on_state, args.nats_url)
    await client.connect()
    await client.join(args.username)

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(_demo())
