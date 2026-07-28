from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from src.rendering.img import Img

from client.ui.app.online_coordinator import OnlineCoordinator
from client.ui.screens.screen_manager import Screen

# ---------------------------------------------------------------------------
# Kung Fu Chess – Home Screen (Auth / Menu)
# ---------------------------------------------------------------------------
# The online client's entry screen: username/password fields plus
# Login/Register buttons — built with cv2 (Img, cv2.rectangle/putText,
# cv2.setMouseCallback, cv2.imshow/waitKey polling), matching this
# codebase's existing login_view.py exactly (same window/field/button
# layout conventions) rather than introducing Pygame or a second GUI
# toolkit — this app already draws 100% of its own UI with raw cv2
# primitives (see ui/graphics/graphics_board_renderer.py), and a second
# windowing event loop competing with cv2's own imshow/waitKey polling
# in the same process is a well-known source of hangs.
#
# Unlike login_view.py (which calls the LOCAL server.database straight
# through and gets an immediate result), this screen's Login/Register
# actions are NETWORK requests: OnlineCoordinator.login()/register()
# only ever queue a message — the actual accept/reject arrives later,
# via OnlineCoordinator.poll() surfacing either a screen transition
# (LOGIN -> LOBBY, on a successful login) or a pending error (on
# rejection). This screen's loop therefore polls the coordinator every
# frame rather than branching on a synchronous return value.
# ---------------------------------------------------------------------------

WINDOW_NAME = "Kung Fu Chess - Home"
WINDOW_WIDTH = 420
WINDOW_HEIGHT = 340

BACKGROUND_BGRA = (40, 40, 40, 255)
FIELD_BGRA = (60, 60, 60, 255)
FIELD_FOCUSED_BGRA = (90, 70, 70, 255)
FIELD_BORDER_BGRA = (150, 150, 150, 255)
LOGIN_BUTTON_BGRA = (70, 130, 70, 255)
REGISTER_BUTTON_BGRA = (130, 90, 70, 255)
TEXT_WHITE = (255, 255, 255, 255)
TEXT_HINT = (170, 170, 170, 255)
TEXT_ERROR_BGRA = (80, 80, 240, 255)
TEXT_SUCCESS_BGRA = (120, 220, 120, 255)

ESC = 27
ENTER = 13
BACKSPACE = 8
TAB = 9

MAX_FIELD_LENGTH = 32  # UI-only typing cap

USERNAME_BOX = (30, 95, WINDOW_WIDTH - 30, 130)
PASSWORD_BOX = (30, 160, WINDOW_WIDTH - 30, 195)
LOGIN_BUTTON = (30, 220, 195, 260)
REGISTER_BUTTON = (215, 220, WINDOW_WIDTH - 30, 260)


def _point_in_box(x: int, y: int, box: "tuple[int, int, int, int]") -> bool:
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


class _HomeScreenState:
    """Everything one ``run_home_screen()`` call needs across frames."""

    def __init__(self) -> None:
        self.username = ""
        self.password = ""
        self.focus = "username"
        self.message = ""
        self.is_error = False
        self.pending_clicks: "list[tuple[int, int]]" = []


def run_home_screen(coordinator: OnlineCoordinator) -> bool:
    """Run the Home (Auth/Menu) screen until the player logs in
    (returns True, having already driven ``coordinator``'s screen to
    ``Screen.LOBBY``) or cancels via Esc (returns False).

    Register does not log the player in automatically — a successful
    registration shows a confirmation message and stays on this
    screen, exactly one network round trip at a time, matching
    ``OnlineCoordinator``'s own Register/Login split (see that
    class's docstring).
    """
    state = _HomeScreenState()

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            state.pending_clicks.append((x, y))

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, on_mouse)
    screen = Img()

    try:
        while True:
            coordinator.poll()
            if coordinator.screens.current is Screen.LOBBY:
                return True

            for err in coordinator.pop_errors():
                state.message = f"Login failed: {err}"
                state.is_error = True

            _render(screen, state)
            cv2.imshow(WINDOW_NAME, screen.img)
            key = cv2.waitKey(30)

            action = None
            for x, y in state.pending_clicks:
                target = _click_target(x, y)
                if target in ("username", "password"):
                    state.focus = target
                elif target in ("login", "register"):
                    action = target
            state.pending_clicks.clear()

            if key == ESC:
                return False
            elif key == TAB:
                state.focus = "password" if state.focus == "username" else "username"
            elif key == BACKSPACE:
                _backspace(state)
            elif key == ENTER:
                action = action or "login"
            elif 32 <= key <= 126:
                _type_char(state, chr(key))

            if action is not None:
                _attempt(state, action, coordinator)
    finally:
        cv2.destroyWindow(WINDOW_NAME)


def _click_target(x: int, y: int) -> Optional[str]:
    if _point_in_box(x, y, USERNAME_BOX):
        return "username"
    if _point_in_box(x, y, PASSWORD_BOX):
        return "password"
    if _point_in_box(x, y, LOGIN_BUTTON):
        return "login"
    if _point_in_box(x, y, REGISTER_BUTTON):
        return "register"
    return None


def _type_char(state: _HomeScreenState, ch: str) -> None:
    if state.focus == "username" and len(state.username) < MAX_FIELD_LENGTH:
        state.username += ch
    elif state.focus == "password" and len(state.password) < MAX_FIELD_LENGTH:
        state.password += ch


def _backspace(state: _HomeScreenState) -> None:
    if state.focus == "username":
        state.username = state.username[:-1]
    else:
        state.password = state.password[:-1]


def _attempt(state: _HomeScreenState, action: str, coordinator: OnlineCoordinator) -> None:
    """Validate the current fields and send a Login or Register request
    — the actual accept/reject arrives later via ``coordinator.poll()``
    (see ``run_home_screen``'s own loop), not synchronously here.
    """
    username, password = state.username.strip(), state.password
    if not username or not password:
        state.message = "Username and password cannot be empty."
        state.is_error = True
        return

    state.is_error = False
    if action == "login":
        state.message = "Logging in..."
        coordinator.login(username, password)
    else:
        state.message = "Registering..."
        coordinator.register(username, password)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render(screen: Img, state: _HomeScreenState) -> None:
    screen.img = np.full((WINDOW_HEIGHT, WINDOW_WIDTH, 4), BACKGROUND_BGRA, dtype=np.uint8)

    screen.put_text("Kung Fu Chess - Online", 30, 40, font_size=0.8, color=TEXT_WHITE, thickness=2)
    screen.put_text("Log in or Register", 30, 68, font_size=0.55, color=TEXT_HINT)

    screen.put_text("Username", USERNAME_BOX[0], USERNAME_BOX[1] - 8, font_size=0.4, color=TEXT_HINT)
    _draw_field(screen, USERNAME_BOX, state.username, state.focus == "username", mask=False)
    screen.put_text("Password", PASSWORD_BOX[0], PASSWORD_BOX[1] - 8, font_size=0.4, color=TEXT_HINT)
    _draw_field(screen, PASSWORD_BOX, state.password, state.focus == "password", mask=True)

    _draw_button(screen, LOGIN_BUTTON, "Login", LOGIN_BUTTON_BGRA)
    _draw_button(screen, REGISTER_BUTTON, "Register", REGISTER_BUTTON_BGRA)

    if state.message:
        color = TEXT_ERROR_BGRA if state.is_error else TEXT_SUCCESS_BGRA
        screen.put_text(state.message, 30, 290, font_size=0.48, color=color)

    screen.put_text(
        "Tab: switch field   Enter: login   Esc: quit",
        30, WINDOW_HEIGHT - 15, font_size=0.4, color=TEXT_HINT,
    )


def _draw_field(screen: Img, box: "tuple[int, int, int, int]", text: str, focused: bool, mask: bool) -> None:
    x1, y1, x2, y2 = box
    cv2.rectangle(screen.img, (x1, y1), (x2, y2), FIELD_FOCUSED_BGRA if focused else FIELD_BGRA, -1)
    cv2.rectangle(screen.img, (x1, y1), (x2, y2), FIELD_BORDER_BGRA, 1)
    shown = "*" * len(text) if mask else text
    screen.put_text(shown, x1 + 8, y2 - 10, font_size=0.5, color=TEXT_WHITE)


def _draw_button(screen: Img, box: "tuple[int, int, int, int]", label: str, color: "tuple[int, int, int, int]") -> None:
    x1, y1, x2, y2 = box
    cv2.rectangle(screen.img, (x1, y1), (x2, y2), color, -1)
    text_x = x1 + (x2 - x1) // 2 - len(label) * 5
    text_y = y1 + (y2 - y1) // 2 + 6
    screen.put_text(label, text_x, text_y, font_size=0.55, color=TEXT_WHITE, thickness=2)
