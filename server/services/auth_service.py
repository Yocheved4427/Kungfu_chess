from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from server.database.sqlite_db_manager import (
    DEFAULT_DB_PATH,
    UserRecord,
    UserRepository,
    UsernameAlreadyExistsError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kung Fu Chess – Authentication Service
# ---------------------------------------------------------------------------
# Thin service layer over server.database.sqlite_db_manager.UserRepository:
# owns the Register/Login *flow* (input validation, translating a raised
# error or a None result into one consistent AuthResult so a caller
# never has to catch UsernameAlreadyExistsError itself or guess what a
# bare None from authenticate() meant) — it does not touch SQL,
# password hashing, or the schema itself; all of that stays exactly
# where it already is, in sqlite_db_manager.
#
# Deliberately never returns a bare bool/None (same "never a bare bool"
# idiom this codebase already uses for legality checking — see
# engine.rule_engine.MoveResult / server.game.rules.rule_engine.
# MoveLegality): AuthResult.outcome always names exactly why a
# register()/login() call did or didn't succeed.
# ---------------------------------------------------------------------------


class AuthOutcome(Enum):
    """Outcome of an ``AuthService.register``/``login`` call."""
    OK = auto()
    INVALID_INPUT = auto()        # blank/whitespace-only username or password
    USERNAME_TAKEN = auto()       # register() only
    INVALID_CREDENTIALS = auto()  # login() only -- unknown username OR wrong
                                   # password, deliberately not distinguished
                                   # (see UserRepository.authenticate's own
                                   # docstring on why)

    @property
    def is_ok(self) -> bool:
        return self is AuthOutcome.OK


@dataclass(frozen=True)
class AuthResult:
    """Result of an ``AuthService.register``/``login`` call.

    ``user`` is populated iff ``outcome`` is ``AuthOutcome.OK`` — the
    caller's own account record (see ``UserRecord``), including
    ``elo_rating``, but never the password hash (``UserRecord`` itself
    carries ``password_hash``; nothing here re-derives or exposes it
    beyond what ``UserRecord`` already stores for internal use).
    """
    outcome: AuthOutcome
    user: Optional[UserRecord] = None


class AuthService:
    """Registration (Register) and login (Login) flows against the
    user database.

    Holds a ``UserRepository`` (constructor-injectable, same DI idiom
    as ``engine.game.GameEngine``'s own collaborators) rather than the
    module-level ``register_user``/``authenticate_user`` functions —
    this class IS the structured, result-typed alternative to those.
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        user_repository: Optional[UserRepository] = None,
    ) -> None:
        self._users: UserRepository = (
            user_repository if user_repository is not None else UserRepository(db_path)
        )

    def register(self, username: str, password: str) -> AuthResult:
        """Create a new account for *username*/*password*.

        Returns ``AuthOutcome.INVALID_INPUT`` iff either is blank/
        whitespace-only (never reaches the database), ``AuthOutcome.
        USERNAME_TAKEN`` iff *username* is already registered
        (``UserRepository.register``'s ``UsernameAlreadyExistsError``,
        caught here so callers never need to import it themselves), or
        ``AuthOutcome.OK`` with the new account's ``UserRecord``.
        """
        if not self._is_present(username) or not self._is_present(password):
            return AuthResult(AuthOutcome.INVALID_INPUT)

        try:
            user = self._users.register(username, password)
        except UsernameAlreadyExistsError:
            logger.info("Registration rejected: username %r already taken", username)
            return AuthResult(AuthOutcome.USERNAME_TAKEN)

        logger.info("Registered new user %r (user_id=%d)", username, user.user_id)
        return AuthResult(AuthOutcome.OK, user)

    def login(self, username: str, password: str) -> AuthResult:
        """Authenticate *username*/*password* against the stored,
        bcrypt-hashed password.

        Returns ``AuthOutcome.INVALID_INPUT`` iff either is blank/
        whitespace-only, ``AuthOutcome.INVALID_CREDENTIALS`` iff
        *username* doesn't exist OR *password* doesn't match it —
        deliberately not distinguished, so a caller can't leak which
        one it was to whoever is attempting to log in — or
        ``AuthOutcome.OK`` with the account's ``UserRecord``.
        """
        if not self._is_present(username) or not self._is_present(password):
            return AuthResult(AuthOutcome.INVALID_INPUT)

        user = self._users.authenticate(username, password)
        if user is None:
            logger.info("Login rejected for username %r", username)
            return AuthResult(AuthOutcome.INVALID_CREDENTIALS)

        logger.info("Logged in user %r (user_id=%d)", username, user.user_id)
        return AuthResult(AuthOutcome.OK, user)

    @staticmethod
    def _is_present(value: str) -> bool:
        return bool(value) and bool(value.strip())
