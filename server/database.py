from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Sequence

import bcrypt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kung Fu Chess – Persistence Layer (SQLite)
# ---------------------------------------------------------------------------
# Standalone data-access layer for the server: user accounts (bcrypt-
# hashed passwords — see _hash_password/_verify_password) and completed-
# game history. Deliberately knows nothing about chess rules, the
# WebSocket protocol, or GameEngine/GameState — it only reads and writes
# rows. The caller (server/server.py, login_view.py, or whatever drives
# a match) owns move validation and ELO *calculation*; this module only
# *persists* whatever values it's given (see UserRepository.update_elo's
# own docstring) — same "decide vs. do" split this codebase already
# draws elsewhere (e.g. realtime.collision_resolver decides, engine.game
# does).
#
# Two ways to use this module:
#   * UserRepository / GameHistoryRepository — the repository objects,
#     for a caller that wants to construct one and reuse it.
#   * register_user() / authenticate_user() / save_game_result() /
#     update_elo() — thin module-level function wrappers around the
#     same two repositories, for a caller (e.g. login_view.py) that
#     would rather call a plain function than construct a repository
#     object. Both call the same underlying SQL — pick whichever suits
#     the call site, there's no behavioural difference between them.
#
# Every public method opens its own short-lived connection via
# _connection() rather than holding one open for the module's lifetime —
# SQLite connections are cheap to open, and this avoids any cross-
# request connection-sharing pitfalls in a server whose asyncio event
# loop may be servicing many connections at once (see server/server.py).
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = "kungfu_chess.db"


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

def _hash_password(password: str) -> str:
    """Return a bcrypt hash of *password*, as a ``str`` for storage in the
    TEXT ``password_hash`` column.

    ``bcrypt.gensalt()`` generates a fresh random salt per call and
    embeds it in the returned hash itself (unlike this module's previous
    PBKDF2-based scheme, no separate salt column/parameter is needed —
    ``_verify_password`` recovers it from *stored_hash* automatically).

    Note: bcrypt only considers the first 72 BYTES of the input — a
    documented limitation of the algorithm itself, irrelevant for any
    realistic password.
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, stored_hash: str) -> bool:
    """True iff *password* matches *stored_hash*.

    ``bcrypt.checkpw`` extracts the original salt embedded in
    *stored_hash* and compares in constant time internally — no
    separate ``secrets.compare_digest`` call needed here.
    """
    return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))


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


# ---------------------------------------------------------------------------
# Function-style API
# ---------------------------------------------------------------------------
# Thin wrappers around UserRepository/GameHistoryRepository for a caller
# (e.g. login_view.py) that wants plain functions rather than repository
# objects. Each constructs a fresh, short-lived repository per call
# rather than holding one at module scope -- consistent with every
# method above opening its own short-lived connection (see
# _connection's own docstring for why).
# ---------------------------------------------------------------------------

def register_user(username: str, password: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Register a new user. Returns True on success, False if *username*
    is already taken.

    The non-raising sibling of ``UserRepository.register()`` — for a
    caller (e.g. a GUI button handler) that would rather branch on a
    bool than catch ``UsernameAlreadyExistsError``.
    """
    try:
        UserRepository(db_path).register(username, password)
        return True
    except UsernameAlreadyExistsError:
        return False


def authenticate_user(username: str, password: str, db_path: str = DEFAULT_DB_PATH) -> dict | None:
    """Return the user's profile as a plain dict if *username*/*password*
    are valid, else None.

    Deliberately omits ``password_hash`` from the returned dict —
    nothing downstream of a successful login has any legitimate reason
    to hold onto it. Keys: ``user_id``, ``username``, ``elo_rating``,
    ``created_at``.
    """
    user = UserRepository(db_path).authenticate(username, password)
    if user is None:
        return None
    return {
        "user_id": user.user_id,
        "username": user.username,
        "elo_rating": user.elo_rating,
        "created_at": user.created_at,
    }


def save_game_result(
    game_id: str,
    white_player_id: int,
    black_player_id: int,
    winner_id: int | None,
    moves: Sequence[dict],
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Persist one completed game — see ``GameHistoryRepository.save_game``."""
    GameHistoryRepository(db_path).save_game(
        game_id, white_player_id, black_player_id, winner_id, moves
    )


def update_elo(user_id: int, elo_rating: int, db_path: str = DEFAULT_DB_PATH) -> None:
    """Persist *user_id*'s new ELO rating — see ``UserRepository.update_elo``."""
    UserRepository(db_path).update_elo(user_id, elo_rating)


if __name__ == "__main__":
    init_db()
    print(f"Database ready at {DEFAULT_DB_PATH}")
