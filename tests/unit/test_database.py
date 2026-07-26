"""
Unit tests for server/database.py

Scope: UserRepository, GameHistoryRepository, and the module-level
function-style API (register_user/authenticate_user/save_game_result/
update_elo/get_player_stats) — schema init, bcrypt password hashing,
authentication, duplicate-username rejection, and game-history logging.

NOT ":memory:" — every public method in server/database.py opens its
OWN short-lived connection per call (see that module's own header for
why), and SQLite's ":memory:" database is private to the single
connection that created it: a second call reusing the same ":memory:"
path opens a BRAND NEW, empty database, not the same one. Confirmed
empirically before writing this file: ``init_db(":memory:")`` followed
by ``register_user(..., db_path=":memory:")`` raises "no such table:
users", since the table init_db's own connection created never existed
in any OTHER connection. A real (if temporary) file, via pytest's
``tmp_path``, is what this module's actual per-call-connection design
needs to be tested correctly — it gives the same per-test isolation and
automatic cleanup ``:memory:`` was meant to provide, without that gotcha.
"""

from __future__ import annotations

import sqlite3

import bcrypt
import pytest

from server.database import (
    GameHistoryRepository,
    GameRecord,
    UserNotFoundError,
    UserRecord,
    UserRepository,
    UsernameAlreadyExistsError,
    authenticate_user,
    get_player_stats,
    init_db,
    register_user,
    save_game_result,
    update_elo,
)


@pytest.fixture
def db_path(tmp_path) -> str:
    """A freshly initialized, throwaway SQLite file — a distinct one per
    test, auto-cleaned by pytest's own tmp_path teardown."""
    path = str(tmp_path / "test_kungfu_chess.db")
    init_db(path)
    return path


# ===========================================================================
# Schema — init_db
# ===========================================================================

class TestInitDb:
    def test_creates_users_and_game_history_tables(self, tmp_path):
        path = str(tmp_path / "fresh.db")
        init_db(path)
        # NOT `with sqlite3.connect(path) as conn:` -- that commits/rolls
        # back but does NOT close the connection (the exact gotcha
        # server.database._connection's own docstring warns about), so
        # this closes it explicitly instead.
        conn = sqlite3.connect(path)
        try:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            conn.close()
        assert "users" in tables
        assert "game_history" in tables

    def test_safe_to_call_twice(self, tmp_path):
        path = str(tmp_path / "fresh.db")
        init_db(path)
        init_db(path)  # must not raise -- CREATE TABLE IF NOT EXISTS


# ===========================================================================
# UserRepository — registration + bcrypt hashing
# ===========================================================================

class TestUserRepositoryRegister:
    def test_returns_a_user_record_with_defaults(self, db_path):
        user = UserRepository(db_path).register("alice", "hunter2")
        assert isinstance(user, UserRecord)
        assert user.username == "alice"
        assert user.elo_rating == 1200
        assert user.user_id > 0

    def test_password_is_bcrypt_hashed_not_stored_in_plaintext(self, db_path):
        user = UserRepository(db_path).register("alice", "hunter2")
        assert user.password_hash != "hunter2"
        assert user.password_hash.startswith("$2")  # bcrypt's own hash prefix
        assert bcrypt.checkpw(b"hunter2", user.password_hash.encode("utf-8"))

    def test_duplicate_username_raises(self, db_path):
        repo = UserRepository(db_path)
        repo.register("alice", "hunter2")
        with pytest.raises(UsernameAlreadyExistsError):
            repo.register("alice", "a-completely-different-password")

    def test_duplicate_rejection_does_not_change_the_original_hash(self, db_path):
        repo = UserRepository(db_path)
        original = repo.register("alice", "hunter2")
        with pytest.raises(UsernameAlreadyExistsError):
            repo.register("alice", "a-completely-different-password")
        assert repo.get_by_username("alice").password_hash == original.password_hash

    def test_two_different_usernames_both_succeed(self, db_path):
        repo = UserRepository(db_path)
        alice = repo.register("alice", "hunter2")
        bob = repo.register("bob", "swordfish")
        assert alice.user_id != bob.user_id


# ===========================================================================
# UserRepository — lookup + authentication
# ===========================================================================

class TestUserRepositoryAuthenticate:
    def test_correct_password_returns_the_user(self, db_path):
        repo = UserRepository(db_path)
        repo.register("alice", "hunter2")
        result = repo.authenticate("alice", "hunter2")
        assert result is not None
        assert result.username == "alice"

    def test_incorrect_password_returns_none(self, db_path):
        repo = UserRepository(db_path)
        repo.register("alice", "hunter2")
        assert repo.authenticate("alice", "wrong-password") is None

    def test_unknown_username_returns_none(self, db_path):
        assert UserRepository(db_path).authenticate("nobody", "whatever") is None

    def test_get_by_username_and_get_by_id_agree(self, db_path):
        repo = UserRepository(db_path)
        registered = repo.register("alice", "hunter2")
        assert repo.get_by_username("alice") == registered
        assert repo.get_by_id(registered.user_id) == registered

    def test_get_by_username_unknown_returns_none(self, db_path):
        assert UserRepository(db_path).get_by_username("nobody") is None

    def test_get_by_id_unknown_returns_none(self, db_path):
        assert UserRepository(db_path).get_by_id(9999) is None


class TestUserRepositoryUpdateElo:
    def test_updates_and_persists(self, db_path):
        repo = UserRepository(db_path)
        user = repo.register("alice", "hunter2")
        repo.update_elo(user.user_id, 1350)
        assert repo.get_by_id(user.user_id).elo_rating == 1350

    def test_unknown_user_id_raises(self, db_path):
        with pytest.raises(UserNotFoundError):
            UserRepository(db_path).update_elo(9999, 1300)


# ===========================================================================
# GameHistoryRepository
# ===========================================================================

class TestGameHistoryRepository:
    def test_save_and_get_game_round_trips(self, db_path):
        repo = UserRepository(db_path)
        alice = repo.register("alice", "hunter2")
        bob = repo.register("bob", "swordfish")

        games = GameHistoryRepository(db_path)
        moves = [{"piece": "wP", "from": "e2", "to": "e4", "time_ms": 200}]
        games.save_game("game-1", alice.user_id, bob.user_id, alice.user_id, moves)

        record = games.get_game("game-1")
        assert isinstance(record, GameRecord)
        assert record.white_player_id == alice.user_id
        assert record.black_player_id == bob.user_id
        assert record.winner_id == alice.user_id
        assert record.moves == moves

    def test_a_draw_has_no_winner(self, db_path):
        repo = UserRepository(db_path)
        alice = repo.register("alice", "hunter2")
        bob = repo.register("bob", "swordfish")
        GameHistoryRepository(db_path).save_game("game-draw", alice.user_id, bob.user_id, None, [])
        assert GameHistoryRepository(db_path).get_game("game-draw").winner_id is None

    def test_get_game_unknown_returns_none(self, db_path):
        assert GameHistoryRepository(db_path).get_game("no-such-game") is None

    def test_get_games_for_player_includes_both_colours(self, db_path):
        repo = UserRepository(db_path)
        alice = repo.register("alice", "hunter2")
        bob = repo.register("bob", "swordfish")
        carol = repo.register("carol", "letmein")

        games = GameHistoryRepository(db_path)
        games.save_game("g1", alice.user_id, bob.user_id, alice.user_id, [])  # alice white
        games.save_game("g2", bob.user_id, alice.user_id, bob.user_id, [])    # alice black
        games.save_game("g3", bob.user_id, carol.user_id, None, [])          # alice not in this one

        alice_games = games.get_games_for_player(alice.user_id)
        assert {g.game_id for g in alice_games} == {"g1", "g2"}

    def test_most_recently_ended_game_comes_first(self, db_path):
        repo = UserRepository(db_path)
        alice = repo.register("alice", "hunter2")
        bob = repo.register("bob", "swordfish")
        games = GameHistoryRepository(db_path)
        games.save_game("first", alice.user_id, bob.user_id, None, [])
        games.save_game("second", alice.user_id, bob.user_id, None, [])
        result = games.get_games_for_player(alice.user_id)
        # ended_at has second-resolution granularity, so this only
        # checks the *some* stable order is returned, not a strict
        # timestamp comparison between two saves microseconds apart.
        assert {g.game_id for g in result} == {"first", "second"}

    def test_foreign_key_violation_on_an_unknown_player_id_raises(self, db_path):
        with pytest.raises(sqlite3.IntegrityError):
            GameHistoryRepository(db_path).save_game("bad-game", 999, 998, None, [])


# ===========================================================================
# Function-style API
# ===========================================================================

class TestRegisterUserFunction:
    def test_returns_true_on_success(self, db_path):
        assert register_user("alice", "hunter2", db_path=db_path) is True

    def test_returns_false_on_duplicate_username(self, db_path):
        register_user("alice", "hunter2", db_path=db_path)
        assert register_user("alice", "a-different-password", db_path=db_path) is False


class TestAuthenticateUserFunction:
    def test_returns_a_plain_dict_without_password_hash(self, db_path):
        register_user("alice", "hunter2", db_path=db_path)
        profile = authenticate_user("alice", "hunter2", db_path=db_path)
        assert profile is not None
        assert profile["username"] == "alice"
        assert profile["elo_rating"] == 1200
        assert "password_hash" not in profile

    def test_wrong_password_returns_none(self, db_path):
        register_user("alice", "hunter2", db_path=db_path)
        assert authenticate_user("alice", "wrong-password", db_path=db_path) is None

    def test_unknown_username_returns_none(self, db_path):
        assert authenticate_user("nobody", "whatever", db_path=db_path) is None


class TestUpdateEloFunction:
    def test_persists(self, db_path):
        register_user("alice", "hunter2", db_path=db_path)
        user_id = authenticate_user("alice", "hunter2", db_path=db_path)["user_id"]
        update_elo(user_id, 1400, db_path=db_path)
        assert authenticate_user("alice", "hunter2", db_path=db_path)["elo_rating"] == 1400


class TestSaveGameResultAndPlayerStats:
    def test_wins_losses_and_draws_are_counted_correctly(self, db_path):
        register_user("alice", "hunter2", db_path=db_path)
        register_user("bob", "swordfish", db_path=db_path)
        alice_id = authenticate_user("alice", "hunter2", db_path=db_path)["user_id"]
        bob_id = authenticate_user("bob", "swordfish", db_path=db_path)["user_id"]

        save_game_result("g1", alice_id, bob_id, alice_id, [{"from": "e2", "to": "e4"}], db_path=db_path)
        save_game_result("g2", alice_id, bob_id, bob_id, [], db_path=db_path)
        save_game_result("g3", alice_id, bob_id, None, [], db_path=db_path)

        assert get_player_stats(alice_id, db_path=db_path) == {
            "games_played": 3, "wins": 1, "losses": 1, "draws": 1,
        }

    def test_a_player_with_no_games_reads_all_zero(self, db_path):
        register_user("alice", "hunter2", db_path=db_path)
        alice_id = authenticate_user("alice", "hunter2", db_path=db_path)["user_id"]
        assert get_player_stats(alice_id, db_path=db_path) == {
            "games_played": 0, "wins": 0, "losses": 0, "draws": 0,
        }
