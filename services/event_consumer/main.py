from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager

import asyncpg
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Kung Fu Chess -- Event Consumer / DB Writer service (services/event_consumer)
# ---------------------------------------------------------------------------
# Server_Design.md decisions 3, 11, 12: a horizontally-scalable pool of
# stateless workers consuming the "game_ended" Kafka topic a Game Server
# publishes to and never touching the database on the real-time hot path
# itself.
#
# Decision 11: applies each player's ELO as a COMMUTATIVE increment
# (elo_rating = elo_rating + delta), not an absolute set -- the Game
# Server already computed the delta, so however two workers' updates for
# the same user interleave, addition gives the same final result either
# way.
#
# Decision 12: the game_history insert + both ELO increments happen in
# ONE database transaction, and the Kafka offset is committed only AFTER
# that transaction commits (enable_auto_commit=False) -- so a crash
# mid-processing means the message is simply redelivered and retried
# whole, never a partial update.
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("event_consumer")

POSTGRES_URI = os.environ.get(
    "POSTGRES_URI",
    "postgresql://kungfu:kungfu_dev_password@postgres:5432/kungfu_chess",
)
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
GAME_ENDED_TOPIC = os.environ.get("GAME_ENDED_TOPIC", "game_ended")
CONSUMER_GROUP = os.environ.get("KAFKA_CONSUMER_GROUP", "event-consumer")


class AppState:
    pg_pool: asyncpg.Pool
    consumer: AIOKafkaConsumer
    consumer_task: asyncio.Task
    running: bool = False
    processed_count: int = 0
    last_processed_at: float | None = None


state = AppState()


async def _persist(payload: dict) -> None:
    white_id = payload.get("white_player_id") or 0
    black_id = payload.get("black_player_id") or 0

    async with state.pg_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO game_history
                    (game_id, white_player_id, black_player_id, winner_id, moves_json)
                VALUES ($1, NULLIF($2, 0), NULLIF($3, 0), $4, $5::jsonb)
                ON CONFLICT (game_id) DO NOTHING
                """,
                payload["game_id"],
                white_id,
                black_id,
                payload.get("winner_id"),
                json.dumps(payload.get("moves", [])),
            )
            if white_id:
                await conn.execute(
                    "UPDATE users SET elo_rating = elo_rating + $1 WHERE user_id = $2",
                    payload.get("white_elo_delta", 0),
                    white_id,
                )
            if black_id:
                await conn.execute(
                    "UPDATE users SET elo_rating = elo_rating + $1 WHERE user_id = $2",
                    payload.get("black_elo_delta", 0),
                    black_id,
                )


async def _consume_loop() -> None:
    async for message in state.consumer:
        try:
            payload = json.loads(message.value)
            await _persist(payload)
            await state.consumer.commit()
            state.processed_count += 1
            state.last_processed_at = time.time()
            logger.info("Persisted game_history + ELO deltas for game_id=%r", payload.get("game_id"))
        except Exception:  # noqa: BLE001
            # Deliberately NOT committed -- per decision 12, this message
            # is redelivered (to this worker or another) and retried
            # whole rather than risking a partial write.
            logger.exception("Failed to process game_ended message; leaving offset uncommitted for redelivery")
            await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.pg_pool = await asyncpg.create_pool(POSTGRES_URI, min_size=1, max_size=5)

    state.consumer = AIOKafkaConsumer(
        GAME_ENDED_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=CONSUMER_GROUP,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    for attempt in range(1, 11):
        try:
            await state.consumer.start()
            break
        except KafkaConnectionError:
            logger.warning("Kafka not ready yet (attempt %d/10); retrying in 3s", attempt)
            await asyncio.sleep(3)
    else:
        raise RuntimeError(f"Could not connect to Kafka at {KAFKA_BOOTSTRAP_SERVERS}")

    state.running = True
    state.consumer_task = asyncio.create_task(_consume_loop())
    logger.info("Event consumer subscribed to %r on %s", GAME_ENDED_TOPIC, KAFKA_BOOTSTRAP_SERVERS)
    try:
        yield
    finally:
        state.running = False
        state.consumer_task.cancel()
        await state.consumer.stop()
        await state.pg_pool.close()


app = FastAPI(title="Kung Fu Chess -- Event Consumer", lifespan=lifespan)


@app.get("/health")
async def health() -> JSONResponse:
    checks = {"postgres": False, "kafka_consumer_running": state.running}
    try:
        async with state.pg_pool.acquire() as conn:
            checks["postgres"] = (await conn.fetchval("SELECT 1")) == 1
    except Exception as e:  # noqa: BLE001
        logger.warning("Postgres health check failed: %s", e)

    healthy = all(checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "checks": checks,
            "processed_count": state.processed_count,
            "last_processed_at": state.last_processed_at,
        },
    )
