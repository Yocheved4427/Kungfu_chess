from __future__ import annotations

import pathlib
import sys
from typing import Optional

REPO_ROOT = pathlib.Path(__file__).resolve().parent
GRAPHICS_DIR = REPO_ROOT / "ui" / "graphics"
# img.py imports its own flat siblings (e.g. `from img import Img` is
# itself imported flatly here), which only resolves if ui/graphics is on
# sys.path -- same setup main_gui.py's own top-of-file comment explains.
# Done here too (not just relied on via main_gui.py having already done
# it) so this module also works if imported/run on its own.
sys.path.insert(0, str(GRAPHICS_DIR))

import cv2
import numpy as np

from img import Img

from server.database.sqlite_db_manager import (
    DEFAULT_DB_PATH,
    authenticate_user,
    init_db,
    register_user,
)

# ---------------------------------------------------------------------------
# Kung Fu Chess – Login / Registration screen
# ---------------------------------------------------------------------------
# Built with cv2 (Img, cv2.rectangle/putText, cv2.setMouseCallback,
# cv2.imshow/waitKey polling) -- matching main_gui.py's own rendering
# conventions exactly, rather than introducing Tkinter or Pygame. This
# app already draws 100% of its own UI (panels, buttons, overlays) with
# raw cv2 primitives (see ui/graphics/graphics_board_renderer.py); a
# login screen is no different in kind. Mixing in a second GUI toolkit
# would also mean two separate windowing event loops (Tkinter's mainloop
# vs. cv2's imshow/waitKey polling) competing in the same process, which
# is a well-known source of hangs/unresponsive windows.
#
# run_login_screen() owns its OWN window start-to-finish: opens it, runs
# its own event loop, destroys it before returning. That makes it safe
# to call more than once in a row (main_gui.py's --two-player mode needs
# one login per side, sequentially) without leaking a window or
# colliding with the game window ui/game_loop.py opens afterward.
# ---------------------------------------------------------------------------

WINDOW_NAME = "Kung Fu Chess - Login"
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
TEXT_ERROR_BGRA = (80, 80, 240, 255)   # red, in BGRA
TEXT_SUCCESS_BGRA = (120, 220, 120, 255)

ESC = 27
ENTER = 13
BACKSPACE = 8
TAB = 9

MAX_FIELD_LENGTH = 32  # UI-only typing cap -- not a database constraint

# (x1, y1, x2, y2) click/draw regions, fixed for this window's fixed size.
USERNAME_BOX = (30, 95, WINDOW_WIDTH - 30, 130)
PASSWORD_BOX = (30, 160, WINDOW_WIDTH - 30, 195)
LOGIN_BUTTON = (30, 220, 195, 260)
REGISTER_BUTTON = (215, 220, WINDOW_WIDTH - 30, 260)


def _point_in_box(x: int, y: int, box: "tuple[int, int, int, int]") -> bool:
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


class _LoginScreenState:
    """Everything one ``run_login_screen()`` call needs across frames.

    A fresh instance per call (never reused) -- so --two-player mode's
    second login starts with empty fields and no leftover error message
    from the first.
    """

    def __init__(self) -> None:
        self.username = ""
        self.password = ""
        self.focus = "username"  # or "password"
        self.message = ""
        self.is_error = False
        self.pending_clicks: "list[tuple[int, int]]" = []


def run_login_screen(
    prompt: str = "Log in or Register",
    db_path: str = DEFAULT_DB_PATH,
    exclude_user_id: Optional[int] = None,
) -> Optional[dict]:
    """Run a self-contained login/registration window; block until the
    player logs in, registers, or cancels.

    *prompt* is shown above the fields — e.g. "White: log in" / "Black:
    log in" for --two-player mode's two separate logins (see
    main_gui.py). *exclude_user_id*, if given, rejects a successful
    login/registration that resolves to that same user_id — used so
    Black can't accidentally log in as the account White just used
    (which would attribute a game_history row's white_player_id and
    black_player_id to the very same user).

    Returns the authenticated user's profile dict (see
    ``server.database.sqlite_db_manager.authenticate_user``) on success, or ``None`` if
    the player closed the window (Esc) instead — the caller is expected
    to abort startup entirely in that case.
    """
    init_db(db_path)  # safe/cheap to call every time -- CREATE TABLE IF NOT EXISTS
    state = _LoginScreenState()

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            state.pending_clicks.append((x, y))

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, on_mouse)
    screen = Img()

    try:
        while True:
            _render(screen, state, prompt)
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
                return None
            elif key == TAB:
                state.focus = "password" if state.focus == "username" else "username"
            elif key == BACKSPACE:
                _backspace(state)
            elif key == ENTER:
                action = action or "login"
            elif 32 <= key <= 126:
                _type_char(state, chr(key))

            if action is not None:
                result = _attempt(state, action, db_path, exclude_user_id)
                if result is not None:
                    return result
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


def _type_char(state: _LoginScreenState, ch: str) -> None:
    if state.focus == "username" and len(state.username) < MAX_FIELD_LENGTH:
        state.username += ch
    elif state.focus == "password" and len(state.password) < MAX_FIELD_LENGTH:
        state.password += ch


def _backspace(state: _LoginScreenState) -> None:
    if state.focus == "username":
        state.username = state.username[:-1]
    else:
        state.password = state.password[:-1]


def _attempt(
    state: _LoginScreenState,
    action: str,
    db_path: str,
    exclude_user_id: Optional[int],
) -> Optional[dict]:
    """Validate the current fields and either log in or register,
    depending on *action* — the one place both the Login/Register
    buttons and the Enter-key shortcut (which always means "login")
    funnel through, so the empty-field/duplicate-username/wrong-
    password/same-account error messages are handled identically
    regardless of how the action was triggered.
    """
    username, password = state.username.strip(), state.password
    if not username or not password:
        state.message = "Username and password cannot be empty."
        state.is_error = True
        return None

    if action == "login":
        user = authenticate_user(username, password, db_path=db_path)
        if user is None:
            state.message = "Incorrect username or password."
            state.is_error = True
            return None
    else:
        if not register_user(username, password, db_path=db_path):
            state.message = f"Username {username!r} is already taken."
            state.is_error = True
            return None
        # Log the new account straight in rather than making the player
        # re-type their credentials a second time.
        user = authenticate_user(username, password, db_path=db_path)

    if exclude_user_id is not None and user is not None and user["user_id"] == exclude_user_id:
        state.message = "That account is already playing in this game."
        state.is_error = True
        return None

    return user


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render(screen: Img, state: _LoginScreenState, prompt: str) -> None:
    screen.img = np.full((WINDOW_HEIGHT, WINDOW_WIDTH, 4), BACKGROUND_BGRA, dtype=np.uint8)

    screen.put_text("Kung Fu Chess", 30, 40, font_size=0.9, color=TEXT_WHITE, thickness=2)
    screen.put_text(prompt, 30, 68, font_size=0.55, color=TEXT_HINT)

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
        "Tab: switch field   Enter: login   Esc: cancel",
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


if __name__ == "__main__":
    from logger_config import setup_logging

    setup_logging()
    profile = run_login_screen()
    print(f"Logged in as: {profile}" if profile else "Login cancelled.")
