from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Set, Tuple

import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from shared.logger_config import setup_logging
from shared.models.board import TextBoard
from shared.models.cell import Cell
from ui.game_factory import STANDARD_BOARD_ROWS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kung Fu Chess -- Spectator Gateway (server/spectator/gateway.py)
# ---------------------------------------------------------------------------
# A separate, independently-deployable service: subscribes to the
# lightweight `game.room.*.diff` Redis Pub/Sub stream
# server/nats/game_server.py publishes on its own 10Hz broadcast cadence,
# and re-broadcasts it to spectator WebSockets -- DELAYED by
# SPECTATOR_DELAY_S seconds, so a spectator never has a real-time
# information edge over the two actual players (e.g. a spectator quietly
# coaching one of them over a side channel).
#
# The Game Server has ZERO knowledge this service exists: it publishes
# to Redis for its own reasons (decoupling "the board changed" from "who,
# if anyone, is watching"), the same way it has no idea how many NATS
# subscribers are listening to its player-facing state subject either.
# This service owns 100% of spectator connection lifecycle -- accepting
# WebSockets, tracking who's watching which room, disconnect cleanup --
# none of which the Game Server's own room-management code needed to
# change even slightly to support.
#
# Reconstructing board state from a pure diff stream: this service holds
# its own `TextBoard` per room, starting from the same STANDARD_BOARD_ROWS
# every game starts from, and applies each diff's changed cells to it via
# `set_piece_at` -- the same mutation primitive shared/models/board.py
# itself uses, not a re-derivation of board semantics. A newly-connecting
# spectator is sent this reconstructed board as an initial snapshot --
# itself never any more current than what's already been released to
# every other spectator, so joining late grants no advantage either.
# ---------------------------------------------------------------------------

DEFAULT_REDIS_HOST = "localhost"
DEFAULT_REDIS_PORT = 6379
DIFF_CHANNEL_PATTERN = "game.room.*.diff"
DEFAULT_SPECTATOR_DELAY_S = 3.0  # 0 disables the delay -- "optional", per spec
FLUSH_INTERVAL_S = 0.1           # how often each room's delay queue is checked for ready messages


@dataclass
class _SpectatorRoom:
    room_id: str
    public_board: TextBoard = field(default_factory=lambda: TextBoard(list(STANDARD_BOARD_ROWS)))
    public_current_time: int = 0
    public_game_over: bool = False
    public_winner: Optional[str] = None
    delay_queue: Deque[Tuple[float, dict]] = field(default_factory=deque)
    spectators: Set[WebSocket] = field(default_factory=set)


class SpectatorGateway:
    """Owns the Redis subscription, the per-room delay queues, the
    reconstructed public board state, and every spectator WebSocket --
    the Game Server touches none of this.
    """

    def __init__(
        self,
        redis_host: str = DEFAULT_REDIS_HOST,
        redis_port: int = DEFAULT_REDIS_PORT,
        delay_s: float = DEFAULT_SPECTATOR_DELAY_S,
    ) -> None:
        self._redis_host = redis_host
        self._redis_port = redis_port
        self._delay_s = delay_s
        self._redis: Optional[redis.Redis] = None
        self._pubsub: Optional["redis.client.PubSub"] = None
        self._rooms: Dict[str, _SpectatorRoom] = {}
        self._listen_task: Optional[asyncio.Task] = None
        self._flush_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._redis = redis.Redis(host=self._redis_host, port=self._redis_port, decode_responses=True)
        await self._redis.ping()
        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe(DIFF_CHANNEL_PATTERN)
        self._listen_task = asyncio.create_task(self._listen_loop())
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info(
            "Spectator gateway connected to redis %s:%d, subscribed to %s (delay=%.1fs)",
            self._redis_host, self._redis_port, DIFF_CHANNEL_PATTERN, self._delay_s,
        )

    async def stop(self) -> None:
        for task in (self._listen_task, self._flush_task):
            if task is not None:
                task.cancel()
        if self._pubsub is not None:
            await self._pubsub.punsubscribe(DIFF_CHANNEL_PATTERN)
            await self._pubsub.aclose()
        if self._redis is not None:
            await self._redis.aclose()

    def configure(self, redis_host: str, redis_port: int, delay_s: float) -> None:
        """Override connection settings before `start()` -- used by the
        `__main__` CLI below, since `gateway` is constructed at module
        import time (before argv is parsed) so FastAPI's route handlers
        have something to close over."""
        self._redis_host = redis_host
        self._redis_port = redis_port
        self._delay_s = delay_s

    def room(self, room_id: str) -> _SpectatorRoom:
        room = self._rooms.get(room_id)
        if room is None:
            room = _SpectatorRoom(room_id=room_id)
            self._rooms[room_id] = room
        return room

    # ------------------------------------------------------------------
    # Redis diff stream -> per-room delay queue
    # ------------------------------------------------------------------

    async def _listen_loop(self) -> None:
        async for message in self._pubsub.listen():
            if message["type"] != "pmessage":
                continue  # subscription-confirmation messages etc.
            channel = message["channel"]
            room_id = channel.split(".")[2]  # game.room.<room_id>.diff
            try:
                payload = json.loads(message["data"])
            except json.JSONDecodeError:
                logger.warning("Malformed diff on %s: %r", channel, message["data"])
                continue

            room = self.room(room_id)
            release_at = time.monotonic() + self._delay_s
            room.delay_queue.append((release_at, payload))

    # ------------------------------------------------------------------
    # Delay queue -> spectator WebSockets (the anti-cheat buffer)
    # ------------------------------------------------------------------

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_S)
            now = time.monotonic()
            for room in list(self._rooms.values()):
                await self._flush_room(room, now)

    async def _flush_room(self, room: _SpectatorRoom, now: float) -> None:
        while room.delay_queue and room.delay_queue[0][0] <= now:
            _, payload = room.delay_queue.popleft()
            self._apply_to_public_state(room, payload)
            if room.spectators:
                await self._broadcast(room, payload)

    def _apply_to_public_state(self, room: _SpectatorRoom, payload: dict) -> None:
        for cell in payload.get("changed_cells", ()):
            room.public_board.set_piece_at(Cell(cell["row"], cell["col"]), cell["piece"])
        room.public_current_time = payload.get("current_time", room.public_current_time)
        room.public_game_over = payload.get("game_over", room.public_game_over)
        room.public_winner = payload.get("winner", room.public_winner)

    async def _broadcast(self, room: _SpectatorRoom, payload: dict) -> None:
        dead: List[WebSocket] = []
        for ws in room.spectators:
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001 -- a broken socket is cleaned up below, not raised
                dead.append(ws)
        for ws in dead:
            room.spectators.discard(ws)

    # ------------------------------------------------------------------
    # Spectator connection lifecycle -- entirely this class's concern
    # ------------------------------------------------------------------

    async def add_spectator(self, room_id: str, ws: WebSocket) -> None:
        room = self.room(room_id)
        room.spectators.add(ws)
        # Sent immediately, but built ENTIRELY from already-released
        # diffs (public_board) -- a spectator who joins mid-game is
        # deliberately given no more information than one who's been
        # watching from the start, same delay guarantee either way.
        await ws.send_json({
            "type": "snapshot",
            "board": room.public_board.get_rows(),
            "current_time": room.public_current_time,
            "game_over": room.public_game_over,
            "winner": room.public_winner,
        })

    def remove_spectator(self, room_id: str, ws: WebSocket) -> None:
        room = self._rooms.get(room_id)
        if room is not None:
            room.spectators.discard(ws)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

gateway = SpectatorGateway()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await gateway.start()
    try:
        yield
    finally:
        await gateway.stop()


app = FastAPI(title="Kung Fu Chess -- Spectator Gateway", lifespan=lifespan)


@app.get("/health")
async def health() -> JSONResponse:
    try:
        ok = bool(await gateway._redis.ping()) if gateway._redis is not None else False
    except Exception as e:  # noqa: BLE001
        logger.warning("Redis health check failed: %s", e)
        ok = False
    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "status": "ok" if ok else "degraded",
            "rooms": len(gateway._rooms),
            "spectators": sum(len(r.spectators) for r in gateway._rooms.values()),
            "delay_s": gateway._delay_s,
        },
    )


@app.websocket("/spectate/{room_id}")
async def spectate(websocket: WebSocket, room_id: str) -> None:
    await websocket.accept()
    await gateway.add_spectator(room_id, websocket)
    logger.info("Spectator connected to room %r", room_id)
    try:
        while True:
            # Spectators are read-only -- this only exists to detect a
            # disconnect (a closed socket raises here); any inbound text
            # is ignored on purpose.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        gateway.remove_spectator(room_id, websocket)
        logger.info("Spectator disconnected from room %r", room_id)


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Kung Fu Chess Spectator Gateway")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--redis-host", default=DEFAULT_REDIS_HOST)
    parser.add_argument("--redis-port", type=int, default=DEFAULT_REDIS_PORT)
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_SPECTATOR_DELAY_S,
        help="Anti-cheat broadcast delay in seconds -- 0 disables it (spec calls this 'optional').",
    )
    args = parser.parse_args()

    gateway.configure(args.redis_host, args.redis_port, args.delay)
    uvicorn.run(app, host=args.host, port=args.port)
