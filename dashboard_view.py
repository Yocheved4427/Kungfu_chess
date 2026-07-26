from __future__ import annotations

import pathlib
import sys
from typing import Optional

REPO_ROOT = pathlib.Path(__file__).resolve().parent
GRAPHICS_DIR = REPO_ROOT / "ui" / "graphics"
# img.py imports its own flat siblings, which only resolves if
# ui/graphics is on sys.path -- same setup login_view.py's own
# top-of-file comment explains. Done here too (not just relied on via
# main_gui.py/login_view.py having already done it) so this module also
# works if imported/run on its own.
sys.path.insert(0, str(GRAPHICS_DIR))

import cv2
import numpy as np

from img import Img

from server.database.sqlite_db_manager import DEFAULT_DB_PATH, UserRepository, get_player_stats

# ---------------------------------------------------------------------------
# Kung Fu Chess – User Dashboard / Lobby screen
# ---------------------------------------------------------------------------
# Shown after a successful login (see login_view.py), before the actual
# game board launches. Built with cv2, same reasoning and conventions as
# login_view.py's own module docstring: this app draws 100% of its own
# UI with raw cv2 primitives already, and a second GUI toolkit's
# mainloop would compete with the game window's own cv2.imshow/waitKey
# polling loop in the same process.
#
# run_dashboard_screen() owns its OWN window start-to-finish (opens it,
# runs its own event loop, destroys it before returning), same as
# run_login_screen() -- safe to call once per player in --two-player
# mode (see main_gui.py) without leaking a window.
#
# NOTE: games_played/wins/losses/draws are read from game_history via
# server.database.sqlite_db_manager.get_player_stats -- nothing in this
# codebase calls save_game_result() yet when a game actually ends
# (that's a separate, not-yet-built piece of wiring in ui/game_loop.py),
# so these will read as all-zero for every player until that exists.
# ELO, by contrast, is already meaningful today (every account starts at
# 1200 and update_elo is fully wired in
# server/database/sqlite_db_manager.py, just not yet called from
# anywhere) -- see get_player_stats' own docstring.
# ---------------------------------------------------------------------------

WINDOW_NAME = "Kung Fu Chess - Dashboard"
WINDOW_WIDTH = 420
WINDOW_HEIGHT = 380

BACKGROUND_BGRA = (40, 40, 40, 255)
STATS_BOX_BGRA = (55, 55, 55, 255)
START_BUTTON_BGRA = (70, 130, 70, 255)
LOGOUT_BUTTON_BGRA = (90, 90, 90, 255)
TEXT_WHITE = (255, 255, 255, 255)
TEXT_HINT = (170, 170, 170, 255)
TEXT_ACCENT = (0, 215, 255, 255)  # gold-ish, BGRA

ESC = 27

STATS_BOX = (30, 100, WINDOW_WIDTH - 30, 230)
START_BUTTON = (30, 250, WINDOW_WIDTH - 30, 292)
LOGOUT_BUTTON = (30, 305, WINDOW_WIDTH - 30, 340)


def _point_in_box(x: int, y: int, box: "tuple[int, int, int, int]") -> bool:
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


def run_dashboard_screen(user: dict, db_path: str = DEFAULT_DB_PATH) -> Optional[str]:
    """Run a self-contained dashboard/lobby window for the already-
    authenticated *user* (the dict ``login_view.run_login_screen``
    returns); block until the player picks an action.

    Fetches *user*'s CURRENT elo_rating fresh from the database (rather
    than trusting the value in *user*, which could be stale if this
    isn't the moment they just logged in) plus games_played/wins/losses/
    draws, once, when the dashboard opens — this is a lobby snapshot,
    not a live-updating view.

    Returns:
        "start"  -- the player clicked "Start New Game".
        "logout" -- the player clicked "Log Out"; the caller is expected
                    to return to the login screen (see main_gui.py).
        None     -- the player closed the window (Esc); the caller is
                    expected to abort startup entirely, same convention
                    as ``run_login_screen``.
    """
    profile = UserRepository(db_path).get_by_id(user["user_id"])
    elo_rating = profile.elo_rating if profile is not None else user.get("elo_rating", 1200)
    stats = get_player_stats(user["user_id"], db_path=db_path)

    pending_clicks: "list[tuple[int, int]]" = []

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            pending_clicks.append((x, y))

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, on_mouse)
    screen = Img()

    try:
        while True:
            _render(screen, user["username"], elo_rating, stats)
            cv2.imshow(WINDOW_NAME, screen.img)
            key = cv2.waitKey(30)

            for x, y in pending_clicks:
                target = _click_target(x, y)
                if target is not None:
                    return target
            pending_clicks.clear()

            if key == ESC:
                return None
    finally:
        cv2.destroyWindow(WINDOW_NAME)


def _click_target(x: int, y: int) -> Optional[str]:
    if _point_in_box(x, y, START_BUTTON):
        return "start"
    if _point_in_box(x, y, LOGOUT_BUTTON):
        return "logout"
    return None


def _render(screen: Img, username: str, elo_rating: int, stats: dict) -> None:
    screen.img = np.full((WINDOW_HEIGHT, WINDOW_WIDTH, 4), BACKGROUND_BGRA, dtype=np.uint8)

    screen.put_text("Kung Fu Chess", 30, 40, font_size=0.9, color=TEXT_WHITE, thickness=2)
    screen.put_text(f"Welcome back, {username}!", 30, 68, font_size=0.6, color=TEXT_ACCENT)

    x1, y1, x2, y2 = STATS_BOX
    cv2.rectangle(screen.img, (x1, y1), (x2, y2), STATS_BOX_BGRA, -1)

    line_x, line_y = x1 + 16, y1 + 30
    screen.put_text(f"ELO Rating: {elo_rating}", line_x, line_y, font_size=0.55, color=TEXT_WHITE)
    line_y += 28
    screen.put_text(f"Games Played: {stats['games_played']}", line_x, line_y, font_size=0.5, color=TEXT_WHITE)
    line_y += 24
    screen.put_text(f"Wins: {stats['wins']}", line_x, line_y, font_size=0.5, color=TEXT_WHITE)
    line_y += 24
    screen.put_text(f"Losses: {stats['losses']}", line_x, line_y, font_size=0.5, color=TEXT_WHITE)
    line_y += 24
    screen.put_text(f"Draws: {stats['draws']}", line_x, line_y, font_size=0.5, color=TEXT_WHITE)

    _draw_button(screen, START_BUTTON, "Start New Game", START_BUTTON_BGRA)
    _draw_button(screen, LOGOUT_BUTTON, "Log Out", LOGOUT_BUTTON_BGRA)

    screen.put_text("Esc: quit", 30, WINDOW_HEIGHT - 15, font_size=0.4, color=TEXT_HINT)


def _draw_button(screen: Img, box: "tuple[int, int, int, int]", label: str, color: "tuple[int, int, int, int]") -> None:
    x1, y1, x2, y2 = box
    cv2.rectangle(screen.img, (x1, y1), (x2, y2), color, -1)
    text_x = x1 + (x2 - x1) // 2 - len(label) * 5
    text_y = y1 + (y2 - y1) // 2 + 6
    screen.put_text(label, text_x, text_y, font_size=0.55, color=TEXT_WHITE, thickness=2)


if __name__ == "__main__":
    from logger_config import setup_logging

    setup_logging()
    demo_user = {"user_id": 0, "username": "demo", "elo_rating": 1200, "created_at": ""}
    print(f"Action: {run_dashboard_screen(demo_user)}")
