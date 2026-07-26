from __future__ import annotations

from enum import Enum, auto
from typing import Callable, Dict, FrozenSet, List

# ---------------------------------------------------------------------------
# Kung Fu Chess – Screen Manager
# ---------------------------------------------------------------------------
# Tracks which screen is currently active and validates transitions
# between them — a plain state machine, nothing more. No rendering,
# no cv2/Tkinter/socket knowledge of its own: whatever actually draws
# each screen (in the spirit of this codebase's existing
# login_view.py/dashboard_view.py cv2 screens, or a future equivalent
# for this new client stack) owns its own window/event loop, exactly
# as those already do; this class only owns "which one is current" and
# "is this transition allowed", via a small, explicit transition table
# rather than each screen independently deciding what it may navigate
# to.
#
# Listener-based (``add_listener``) rather than the UI polling
# ``current`` every frame for a change: a caller (e.g.
# client.ui.app.online_coordinator.OnlineCoordinator) reacts to a
# transition exactly once, when it happens, the same "push, not poll"
# idiom this codebase's ``ui.bus.Bus``/``Observer`` already uses for
# GameEvent notifications.
# ---------------------------------------------------------------------------


class Screen(Enum):
    """A screen the client can be showing."""
    MAIN_MENU = auto()
    LOGIN = auto()
    LOBBY = auto()  # room list / create-or-join / matchmaking queue
    GAME = auto()   # active game board


_ALLOWED_TRANSITIONS: Dict[Screen, FrozenSet[Screen]] = {
    Screen.MAIN_MENU: frozenset({Screen.LOGIN}),
    Screen.LOGIN: frozenset({Screen.MAIN_MENU, Screen.LOBBY}),
    Screen.LOBBY: frozenset({Screen.MAIN_MENU, Screen.GAME}),
    Screen.GAME: frozenset({Screen.LOBBY, Screen.MAIN_MENU}),
}

_ScreenListener = Callable[[Screen, Screen], None]


class ScreenManager:
    """Navigates between ``Screen.MAIN_MENU``, ``LOGIN``, ``LOBBY``, and
    ``GAME`` — the only transitions this app's flow ever needs
    (Main Menu -> Login on "play online"; Login -> Lobby on a
    successful login, or back to Main Menu on cancel; Lobby -> Game
    once a room's second player joins, or back to Main Menu on
    log-out; Game -> Lobby once a finished game is dismissed, or
    straight back to Main Menu on quit).
    """

    def __init__(self, initial: Screen = Screen.MAIN_MENU) -> None:
        self._current = initial
        self._listeners: List[_ScreenListener] = []

    @property
    def current(self) -> Screen:
        return self._current

    def can_transition_to(self, target: Screen) -> bool:
        """True iff *target* is reachable directly from the current screen."""
        return target in _ALLOWED_TRANSITIONS.get(self._current, frozenset())

    def transition_to(self, target: Screen) -> bool:
        """Move to *target* iff legal from the current screen.

        Returns True iff the transition happened, notifying every
        registered listener with ``(old, new)`` on success. An illegal
        transition is a no-op that returns False rather than raising —
        a UI event arriving for a screen the app has already navigated
        away from is a normal race (e.g. a stale button callback), not
        a bug worth crashing over.
        """
        if not self.can_transition_to(target):
            return False
        old = self._current
        self._current = target
        for listener in self._listeners:
            listener(old, target)
        return True

    def add_listener(self, listener: _ScreenListener) -> None:
        """Register *listener* to be called ``listener(old, new)`` on
        every successful transition, in registration order."""
        self._listeners.append(listener)
