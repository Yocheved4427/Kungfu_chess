from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from src.rendering.img import Img

from client.ui.app.online_coordinator import OnlineCoordinator
from client.ui.screens.screen_manager import Screen

# ---------------------------------------------------------------------------
# Kung Fu Chess – Room Screen (Lobby / Rooms)
# ---------------------------------------------------------------------------
# Shown after a successful login (Screen.LOBBY): create a room, join an
# existing one by id, or queue for ELO-based matchmaking (see
# server.services.room_service/matchmaking_service). Same cv2
# rendering conventions as home_screen.py/login_view.py/
# dashboard_view.py — one more screen in the same, already-established
# style, not a second UI approach.
#
# Every action here (create_room/join_room/queue_for_match) is a fire-
# and-forget network request, same as home_screen.py's Login/Register —
# the actual room_id/match result arrives later via
# OnlineCoordinator.poll(), read off coordinator.room_id, or via a
# GameStateUpdateMessage flipping the screen straight to Screen.GAME
# once the room's second player joins (see OnlineCoordinator._handle).
# ---------------------------------------------------------------------------

WINDOW_NAME = "Kung Fu Chess - Lobby"
WINDOW_WIDTH = 460
WINDOW_HEIGHT = 380

BACKGROUND_BGRA = (40, 40, 40, 255)
FIELD_BGRA = (60, 60, 60, 255)
FIELD_FOCUSED_BGRA = (90, 70, 70, 255)
FIELD_BORDER_BGRA = (150, 150, 150, 255)
CREATE_BUTTON_BGRA = (70, 130, 70, 255)
JOIN_BUTTON_BGRA = (70, 100, 150, 255)
MATCH_BUTTON_BGRA = (130, 90, 150, 255)
LOGOUT_BUTTON_BGRA = (90, 90, 90, 255)
TEXT_WHITE = (255, 255, 255, 255)
TEXT_HINT = (170, 170, 170, 255)
TEXT_ERROR_BGRA = (80, 80, 240, 255)
TEXT_SUCCESS_BGRA = (120, 220, 120, 255)

ESC = 27
BACKSPACE = 8
TAB = 9

MAX_FIELD_LENGTH = 32

ROOM_NAME_BOX = (30, 105, WINDOW_WIDTH - 30, 138)
CREATE_BUTTON = (30, 148, WINDOW_WIDTH - 30, 182)

ROOM_ID_BOX = (30, 225, WINDOW_WIDTH - 30, 258)
JOIN_BUTTON = (30, 268, WINDOW_WIDTH - 30, 302)

MATCH_BUTTON = (30, 318, 280, 352)
LOGOUT_BUTTON = (300, 318, WINDOW_WIDTH - 30, 352)


def _point_in_box(x: int, y: int, box: "tuple[int, int, int, int]") -> bool:
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


class _RoomScreenState:
    def __init__(self) -> None:
        self.room_name = "New Room"
        self.room_id_to_join = ""
        self.focus = "room_name"  # or "room_id"
        self.message = ""
        self.is_error = False
        self.pending_clicks: "list[tuple[int, int]]" = []


def run_room_screen(coordinator: OnlineCoordinator) -> bool:
    """Run the Lobby screen until a room's game starts (returns True,
    ``coordinator.screens.current`` is already ``Screen.GAME``) or the
    player logs out via the Logout button/Esc (returns False, screen is
    back at ``Screen.MAIN_MENU``).
    """
    state = _RoomScreenState()

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            state.pending_clicks.append((x, y))

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, on_mouse)
    screen = Img()

    try:
        while True:
            coordinator.poll()
            if coordinator.screens.current is Screen.GAME:
                return True

            for err in coordinator.pop_errors():
                state.message = err
                state.is_error = True

            if coordinator.room_id is not None and not state.message:
                state.message = f"In room {coordinator.room_id} -- waiting for an opponent..."
                state.is_error = False

            _render(screen, state, coordinator)
            cv2.imshow(WINDOW_NAME, screen.img)
            key = cv2.waitKey(30)

            action = None
            for x, y in state.pending_clicks:
                target = _click_target(x, y)
                if target in ("room_name", "room_id"):
                    state.focus = target
                elif target is not None:
                    action = target
            state.pending_clicks.clear()

            if key == ESC:
                coordinator.log_out()
                return False
            elif key == TAB:
                state.focus = "room_id" if state.focus == "room_name" else "room_name"
            elif key == BACKSPACE:
                _backspace(state)
            elif 32 <= key <= 126:
                _type_char(state, chr(key))

            if action == "create_room":
                coordinator.create_room(state.room_name.strip() or "Room")
                state.message = "Creating room..."
                state.is_error = False
            elif action == "join_room":
                if state.room_id_to_join.strip():
                    coordinator.join_room(state.room_id_to_join.strip())
                    state.message = "Joining room..."
                    state.is_error = False
            elif action == "queue_for_match":
                coordinator.queue_for_match()
                state.message = "Searching for an opponent..."
                state.is_error = False
            elif action == "log_out":
                coordinator.log_out()
                return False
    finally:
        cv2.destroyWindow(WINDOW_NAME)


def _click_target(x: int, y: int) -> Optional[str]:
    if _point_in_box(x, y, ROOM_NAME_BOX):
        return "room_name"
    if _point_in_box(x, y, ROOM_ID_BOX):
        return "room_id"
    if _point_in_box(x, y, CREATE_BUTTON):
        return "create_room"
    if _point_in_box(x, y, JOIN_BUTTON):
        return "join_room"
    if _point_in_box(x, y, MATCH_BUTTON):
        return "queue_for_match"
    if _point_in_box(x, y, LOGOUT_BUTTON):
        return "log_out"
    return None


def _type_char(state: _RoomScreenState, ch: str) -> None:
    if state.focus == "room_name" and len(state.room_name) < MAX_FIELD_LENGTH:
        state.room_name += ch
    elif state.focus == "room_id" and len(state.room_id_to_join) < MAX_FIELD_LENGTH:
        state.room_id_to_join += ch


def _backspace(state: _RoomScreenState) -> None:
    if state.focus == "room_name":
        state.room_name = state.room_name[:-1]
    else:
        state.room_id_to_join = state.room_id_to_join[:-1]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render(screen: Img, state: _RoomScreenState, coordinator: OnlineCoordinator) -> None:
    screen.img = np.full((WINDOW_HEIGHT, WINDOW_WIDTH, 4), BACKGROUND_BGRA, dtype=np.uint8)

    screen.put_text("Lobby", 30, 40, font_size=0.8, color=TEXT_WHITE, thickness=2)
    elo_text = f"ELO: {coordinator.elo_rating}" if coordinator.elo_rating is not None else ""
    screen.put_text(elo_text, WINDOW_WIDTH - 150, 40, font_size=0.5, color=TEXT_HINT)

    screen.put_text("Create a room", ROOM_NAME_BOX[0], ROOM_NAME_BOX[1] - 8, font_size=0.42, color=TEXT_HINT)
    _draw_field(screen, ROOM_NAME_BOX, state.room_name, state.focus == "room_name")
    _draw_button(screen, CREATE_BUTTON, "Create Room", CREATE_BUTTON_BGRA)

    screen.put_text("Join a room by id", ROOM_ID_BOX[0], ROOM_ID_BOX[1] - 8, font_size=0.42, color=TEXT_HINT)
    _draw_field(screen, ROOM_ID_BOX, state.room_id_to_join, state.focus == "room_id")
    _draw_button(screen, JOIN_BUTTON, "Join Room", JOIN_BUTTON_BGRA)

    _draw_button(screen, MATCH_BUTTON, "Quick Match", MATCH_BUTTON_BGRA)
    _draw_button(screen, LOGOUT_BUTTON, "Log Out", LOGOUT_BUTTON_BGRA)

    if state.message:
        color = TEXT_ERROR_BGRA if state.is_error else TEXT_SUCCESS_BGRA
        screen.put_text(state.message, 30, WINDOW_HEIGHT - 30, font_size=0.45, color=color)

    screen.put_text(
        "Tab: switch field   Esc: log out",
        30, WINDOW_HEIGHT - 10, font_size=0.38, color=TEXT_HINT,
    )


def _draw_field(screen: Img, box: "tuple[int, int, int, int]", text: str, focused: bool) -> None:
    x1, y1, x2, y2 = box
    cv2.rectangle(screen.img, (x1, y1), (x2, y2), FIELD_FOCUSED_BGRA if focused else FIELD_BGRA, -1)
    cv2.rectangle(screen.img, (x1, y1), (x2, y2), FIELD_BORDER_BGRA, 1)
    screen.put_text(text, x1 + 8, y2 - 9, font_size=0.48, color=TEXT_WHITE)


def _draw_button(screen: Img, box: "tuple[int, int, int, int]", label: str, color: "tuple[int, int, int, int]") -> None:
    x1, y1, x2, y2 = box
    cv2.rectangle(screen.img, (x1, y1), (x2, y2), color, -1)
    text_x = x1 + (x2 - x1) // 2 - len(label) * 5
    text_y = y1 + (y2 - y1) // 2 + 6
    screen.put_text(label, text_x, text_y, font_size=0.5, color=TEXT_WHITE, thickness=2)
