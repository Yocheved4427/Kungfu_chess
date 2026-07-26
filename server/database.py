from __future__ import annotations

import hashlib
import json
import logging
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kung Fu Chess – Persistence Layer (SQLite)
# ---------------------------------------------------------------------------
# Standalone data-access layer for the server: user accounts (salted,
# hashed passwords — see _hash_password/_verify_password) and completed-
# game history. Deliberately knows nothing about chess rules, the
# WebSocket protocol, or GameEngine/GameState — it only reads and writes
# rows. The caller (server/server.py, or whatever drives a match) owns
# move validation and ELO *calculation*; this module only *persists*
# whatever values it's given (see UserRepository.update_elo's own
# docstring) — same "decide vs. do" split this codebase already draws
# elsewhere (e.g. realtime.collision_resolver decides, engine.game does).
#
# Every public method opens its own short-lived connection via
# _connection() rather than holding one open for the module's lifetime —
# SQLite connections are cheap to open, and this avoids any cross-
# request connection-sharing pitfalls in a server whose asyncio event
# loop may be servicing many connections at once (see server/server.py).
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = "kungfu_chess.db"

# PBKDF2-HMAC-SHA256 iteration count — OWASP's 2023 minimum recommendation
# for this specific algorithm. Deliberately not sha256(password) alone,
# which has no per-user salt and is fast enough to brute-force at scale.
_PBKDF2_ITERATIONS = 260_000
_SALT_BYTES = 16


class UsernameAlreadyExistsError(Exception):
    """Raised by ``UserRepository.register()`` when *username* is already taken."""


class UserNotFoundError(Exception):
    """Raised when an operation needs an existing ``user_id`` that has no matching row."""


@dataclass(frozen=True)
class UserRecord:
    """One row of the ``users`` table.

    Carries ``password_hash`` (the stored ``"<salt_hex>$<hash_hex>"``
    string), never the raw password — nothing in this module ever holds
    a plaintext password longer than the single call that hashes or
    verifies it.
    """
    user_id: int
    username: str
    password_hash: str
    elo_rating: int
    created_at: str


@dataclass(frozen=True)
class GameRecord:
    """One row of the ``game_history`` table.

    ``moves`` is already decoded from the stored ``moves_json`` column —
    see ``GameHistoryRepository.get_game``. ``winner_id`` is ``None`` for
    a draw.
    """
    game_id: str
    white_player_id: int
    black_player_id: int
    winner_id: int | None
    moves: list
    ended_at: str


# ---------------------------------------------------------------------------
# Connection handling
# ---------------------------------------------------------------------------

@contextmanager
def _connection(db_path: str) -> Iterator[sqlite3.Connection]:
    """Open a connection for exactly one unit of work.

    Enforces foreign keys (off by default per-connection in SQLite) and
    returns rows as ``sqlite3.Row`` (supports both index and column-name
    access, e.g. ``row["username"]``). The transaction auto-commits on a
    clean exit or rolls back on an exception, via the inner
    ``with conn:`` — but that alone does NOT close the connection (a
    common gotcha with bare ``with sqlite3.connect(...) as conn:``), so
    the outer ``try/finally`` guarantees it's closed either way.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        with conn:
            yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: bytes | None = None) -> str:
    """Return ``"<salt_hex>$<hash_hex>"`` for *password*.

    PBKDF2-HMAC-SHA256 with a fresh random salt, unless *salt* is given
    (verification against an existing hash — see ``_verify_password``,
    which reuses the ORIGINAL salt rather than generating a new one).
    """
    if salt is None:
        salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    """True iff *password*, hashed with the salt embedded in
    *stored_hash*, reproduces *stored_hash* exactly.

    Uses ``secrets.compare_digest`` (constant-time) rather than ``==``,
    so how many leading bytes matched can't leak via a timing side-channel.
    """
    salt_hex, _, _ = stored_hash.partition("$")
    salt = bytes.fromhex(salt_hex)
    candidate = _hash_password(password, salt=salt)
    return secrets.compare_digest(candidate, stored_hash)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Create the ``users``/``game_history`` tables if they don't already exist.

    Safe to call every time the server starts — ``CREATE TABLE IF NOT
    EXISTS`` is a no-op against an already-initialized database.
    """
    with _connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                elo_rating    INTEGER DEFAULT 1200,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS game_history (
                game_id         TEXT PRIMARY KEY,
                white_player_id INTEGER,
                black_player_id INTEGER,
                winner_id       INTEGER,
                moves_json      TEXT,
                ended_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (white_player_id) REFERENCES users (user_id),
                FOREIGN KEY (black_player_id) REFERENCES users (user_id),
                FOREIGN KEY (winner_id) REFERENCES users (user_id)
            )
            """
        )
    logger.info("Database initialized at %s", db_path)


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------

class UserRepository:
    """DAO for the ``users`` table: registration, lookup, authentication,
    and ELO persistence. Contains no chess or matchmaking logic — ELO is
    computed elsewhere and only ever *stored* here (see ``update_elo``).
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self._db_path = db_path

    def register(self, username: str, password: str) -> UserRecord:
        """Create a new user with a freshly salted-and-hashed password.

        Raises ``UsernameAlreadyExistsError`` (translated from the
        underlying ``sqlite3.IntegrityError`` on the ``UNIQUE``
        constraint) if *username* is already taken — callers never need
        to import ``sqlite3`` themselves to handle this. The plaintext
        *password* is never stored or logged; only its hash is.
        """
        password_hash = _hash_password(password)
        try:
            with _connection(self._db_path) as conn:
                conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, password_hash),
                )
        except sqlite3.IntegrityError as e:
            raise UsernameAlreadyExistsError(f"Username {username!r} is already taken") from e

        # Re-fetch rather than hand-assembling the record: elo_rating and
        # created_at are both DB-assigned defaults (1200 / CURRENT_TIMESTAMP),
        # so this is the only way to report back what was actually stored.
        user = self.get_by_username(username)
        assert user is not None  # just inserted, within this same call
        logger.info("Registered new user %r (user_id=%d)", username, user.user_id)
        return user

    def get_by_username(self, username: str) -> UserRecord | None:
        """Fetch a user's full row by *username*, or ``None`` if no such user exists."""
        with _connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT user_id, username, password_hash, elo_rating, created_at "
                "FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def get_by_id(self, user_id: int) -> UserRecord | None:
        """Fetch a user's full row by *user_id*, or ``None`` if no such user exists."""
        with _connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT user_id, username, password_hash, elo_rating, created_at "
                "FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def authenticate(self, username: str, password: str) -> UserRecord | None:
        """Return the matching user's record iff *username* exists and
        *password* matches its stored hash.

        Returns ``None`` for either "no such user" or "wrong password"
        without distinguishing them, so a caller can't accidentally leak
        which one it was (e.g. via a different error message) to whoever
        is attempting to log in.
        """
        user = self.get_by_username(username)
        if user is None:
            return None
        if not _verify_password(password, user.password_hash):
            return None
        return user

    def update_elo(self, user_id: int, elo_rating: int) -> None:
        """Persist *user_id*'s new ELO rating.

        A pure setter — this repository never computes a rating itself;
        that's the calling game/matchmaking service's job (the actual
        ELO formula, K-factor, etc.), which passes in the already-
        computed result. Raises ``UserNotFoundError`` if *user_id*
        doesn't exist.
        """
        with _connection(self._db_path) as conn:
            cursor = conn.execute(
                "UPDATE users SET elo_rating = ? WHERE user_id = ?",
                (elo_rating, user_id),
            )
            if cursor.rowcount == 0:
                raise UserNotFoundError(f"No user with user_id={user_id}")
        logger.info("Updated ELO for user_id=%d -> %d", user_id, elo_rating)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> UserRecord:
        return UserRecord(
            user_id=row["user_id"],
            username=row["username"],
            password_hash=row["password_hash"],
            elo_rating=row["elo_rating"],
            created_at=row["created_at"],
        )


class GameHistoryRepository:
    """DAO for the ``game_history`` table: saving a completed game's
    move log and outcome, and reading it back."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self._db_path = db_path

    def save_game(
        self,
        game_id: str,
        white_player_id: int,
        black_player_id: int,
        winner_id: int | None,
        moves: Sequence[dict],
    ) -> None:
        """Persist one completed game.

        *moves* is any JSON-serializable sequence — e.g. a list of
        ``{"piece": ..., "from": ..., "to": ..., "time_ms": ...}``
        dicts — this method only serializes and stores it, it never
        interprets move content (that would be a chess-rules concern,
        out of scope here). *winner_id* is ``None`` for a draw.
        """
        moves_json = json.dumps(list(moves))
        with _connection(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO game_history
                    (game_id, white_player_id, black_player_id, winner_id, moves_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (game_id, white_player_id, black_player_id, winner_id, moves_json),
            )
        logger.info("Saved game_history for game_id=%r", game_id)

    def get_game(self, game_id: str) -> GameRecord | None:
        """Fetch one completed game by *game_id*, or ``None`` if not found."""
        with _connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT game_id, white_player_id, black_player_id, winner_id, "
                "moves_json, ended_at FROM game_history WHERE game_id = ?",
                (game_id,),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def get_games_for_player(self, user_id: int) -> list[GameRecord]:
        """Every completed game *user_id* played in (either colour),
        most recently ended first."""
        with _connection(self._db_path) as conn:
            rows = conn.execute(
                "SELECT game_id, white_player_id, black_player_id, winner_id, "
                "moves_json, ended_at FROM game_history "
                "WHERE white_player_id = ? OR black_player_id = ? "
                "ORDER BY ended_at DESC",
                (user_id, user_id),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> GameRecord:
        return GameRecord(
            game_id=row["game_id"],
            white_player_id=row["white_player_id"],
            black_player_id=row["black_player_id"],
            winner_id=row["winner_id"],
            moves=json.loads(row["moves_json"]) if row["moves_json"] else [],
            ended_at=row["ended_at"],
        )


if __name__ == "__main__":
    init_db()
    print(f"Database ready at {DEFAULT_DB_PATH}")
