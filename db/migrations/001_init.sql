-- Kung Fu Chess -- PostgreSQL schema (local-dev equivalent of
-- server/database/sqlite_db_manager.py's schema, per Server_Design.md
-- decision 1: PostgreSQL replaces SQLite as the durable account/history
-- store; services/event_consumer/ is the only writer, services/gateway/
-- is the only reader+writer for auth).
--
-- Mounted into the postgres container at /docker-entrypoint-initdb.d/,
-- so it runs automatically once, the first time the postgres data
-- volume is created (see docker-compose.yml's postgres service).
--
-- NOTE: this is plain PostgreSQL, not yet sharded with Citus (decision
-- 1's production choice) -- Citus adds nothing for a single-node local
-- dev environment; the schema/query surface below is unchanged either
-- way.

CREATE TABLE IF NOT EXISTS users (
    user_id       SERIAL PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    elo_rating    INTEGER NOT NULL DEFAULT 1200,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS game_history (
    game_id          TEXT PRIMARY KEY,
    white_player_id  INTEGER REFERENCES users (user_id),
    black_player_id  INTEGER REFERENCES users (user_id),
    winner_id        INTEGER REFERENCES users (user_id),
    moves_json       JSONB NOT NULL DEFAULT '[]'::jsonb,
    ended_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_game_history_white_player ON game_history (white_player_id);
CREATE INDEX IF NOT EXISTS idx_game_history_black_player ON game_history (black_player_id);
