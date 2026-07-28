from __future__ import annotations

import pathlib
import time
from typing import List, Optional, Tuple

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

import cv2
import numpy as np

from src.rendering.img import Img

from input.board_mapper import BoardMapper
from shared.models.cell import Cell
from client.ui.animation.animation_manager import AnimationManager
from client.ui.app.online_coordinator import OnlineCoordinator
from client.ui.screens.screen_manager import Screen

# ---------------------------------------------------------------------------
# Kung Fu Chess – Online Game Screen (Active Game view)
# ---------------------------------------------------------------------------
# Renders the board a room's real-time game is playing on, using
# AnimationManager (client.ui.animation.animation_manager) for each
# occupied cell's sprite frame, and input.board_mapper.BoardMapper for
# pixel<->cell arithmetic — the single place that ever happens in this
# codebase (see that module's own docstring); this screen does not
# hand-roll ``x // cell_size`` itself.
#
# There is no local rules engine here at all: OnlineCoordinator.
# latest_board is a flat, already-resolved board snapshot from the
# server (server.network.server.NetworkServer), and move_piece() is a
# bare request — legality is entirely the server's call (see
# server.game.rules.rule_engine.RuleEngine /
# server.game.real_time_arbiter.RealTimeArbiter). An illegal move just
# comes back as an ErrorMessage, surfaced here the same way any other
# error is. Every piece renders as "idle" — the wire protocol carries
# no per-piece transit/airborne/cooldown detail to animate "move"/
# "jump"/rest states from (same accepted limitation as the existing
# root network_client.py / ui.game_loop.py's own --username mode; see
# AnimationManager's own docstring for the full account).
# ---------------------------------------------------------------------------

WINDOW_NAME = "Kung Fu Chess - Online Game"
BOARD_ROWS = 8
BOARD_COLS = 8
ASSETS_ROOT = _REPO_ROOT / "assets" / "pieces1"
BOARD_IMAGE_PATH = _REPO_ROOT / "assets" / "board.png"

BACKGROUND_BGRA = (30, 30, 30, 255)
SELECTED_BORDER_BGRA = (0, 220, 220, 255)
HUD_TEXT_WHITE = (255, 255, 255, 255)
HUD_TEXT_ERROR_BGRA = (80, 80, 240, 255)
GAME_OVER_OVERLAY_BGR = (20, 20, 20)
GAME_OVER_TEXT_WHITE = (255, 255, 255, 255)

ESC = 27
ERROR_DISPLAY_SECONDS = 4.0


class _OnlineClickController:
    """Click handling for this screen: tracks a LOCAL ``selection``
    only (a pure UI/interaction concern) and, on a completed
    selection, sends the move request to the server instead of ever
    mutating a local board — same two-step "click a piece, click a
    destination" shape, and the same same-colour-switches-selection /
    anything-else-attempts-a-move rule, as this codebase's other
    click controllers (``controllers.click_controller.ClickController``,
    the root ``ui/game_loop.py``'s own ``_NetworkClickController``).
    Unlike either of those, there is no colour restriction here at
    all — this client doesn't know its own assigned colour (the wire
    protocol never tells it one; only server/server.py's OLDER,
    separate protocol does), so a click on the wrong colour's piece is
    simply a move request the server will reject.
    """

    def __init__(self, mapper: BoardMapper) -> None:
        self._mapper = mapper
        self.selection: Optional[Cell] = None

    def handle_click(
        self, board_rows: Tuple[str, ...], x: int, y: int, coordinator: OnlineCoordinator
    ) -> None:
        pos = self._mapper.pixel_to_cell(x, y)
        if not (0 <= pos.row < len(board_rows)):
            return
        tokens = board_rows[pos.row].split()
        if not (0 <= pos.col < len(tokens)):
            return

        piece = tokens[pos.col]
        has_piece = piece != "."

        if self.selection is None:
            if has_piece:
                self.selection = pos
            return

        if pos == self.selection:
            self.selection = None  # click the same cell again -- deselect
            return

        from_tokens = board_rows[self.selection.row].split()
        from_piece = from_tokens[self.selection.col]
        coordinator.move_piece(self.selection, pos, from_piece)
        self.selection = None


def run_online_game_screen(coordinator: OnlineCoordinator) -> None:
    """Run the Active Game screen until the player dismisses a
    finished game (any key, once ``coordinator.is_game_over``) or
    quits outright (Esc) — either way, control returns to the caller
    with the screen already back at ``Screen.LOBBY`` or
    ``Screen.MAIN_MENU`` respectively.
    """
    board_native = Img().read(BOARD_IMAGE_PATH)
    mapper = BoardMapper.from_board_pixels(
        board_native.img.shape[1], board_native.img.shape[0], BOARD_COLS, BOARD_ROWS
    )
    cell_size = mapper.cell_size
    board_background = Img().read(
        BOARD_IMAGE_PATH, size=(cell_size * BOARD_COLS, cell_size * BOARD_ROWS)
    )

    animations = AnimationManager(ASSETS_ROOT)
    click_controller = _OnlineClickController(mapper)
    previous_ids: set = set()

    pending_clicks: List[Tuple[int, int]] = []

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            pending_clicks.append((x, y))

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, on_mouse)

    error_message = ""
    error_expires_at = 0.0

    try:
        while coordinator.screens.current is Screen.GAME:
            coordinator.poll()

            for err in coordinator.pop_errors():
                error_message = err
                error_expires_at = time.time() + ERROR_DISPLAY_SECONDS

            board = coordinator.latest_board
            screen = Img()

            if board is not None:
                screen.img = board_background.img.copy()
                for click_x, click_y in pending_clicks:
                    click_controller.handle_click(board, click_x, click_y, coordinator)
                previous_ids = _draw_pieces(screen, animations, board, mapper, previous_ids)
                _draw_selection(screen, click_controller.selection, mapper)
            else:
                screen.img = np.full(
                    (cell_size * BOARD_ROWS, cell_size * BOARD_COLS, 4), BACKGROUND_BGRA, dtype=np.uint8
                )
                screen.put_text(
                    "Waiting for the game to start...",
                    20, (cell_size * BOARD_ROWS) // 2, font_size=0.6, color=HUD_TEXT_WHITE,
                )
            pending_clicks.clear()

            if error_message and time.time() >= error_expires_at:
                error_message = ""
            _draw_hud(screen, coordinator, error_message)

            if coordinator.is_game_over:
                _draw_game_over(screen, coordinator.winner)

            cv2.imshow(WINDOW_NAME, screen.img)
            key = cv2.waitKey(30)

            if key == ESC:
                coordinator.screens.transition_to(Screen.MAIN_MENU)
                break
            if coordinator.is_game_over and key != -1:
                coordinator.return_to_lobby()
    finally:
        cv2.destroyWindow(WINDOW_NAME)


def _draw_pieces(
    screen: Img,
    animations: AnimationManager,
    board_rows: Tuple[str, ...],
    mapper: BoardMapper,
    previous_ids: set,
) -> set:
    """Draw every occupied cell's current animation frame, scaled to
    ``mapper``'s own cell size (matching GraphicsBoardRenderer's exact
    approach: sprites are not natively cell-sized — see AssetLoader's
    own asset files — so each frame is resized before ``draw_on``).

    Returns this frame's set of piece ids actually drawn — the caller
    passes it back in as *previous_ids* next frame so any id that
    disappeared (moved away from its cell, or was captured) gets its
    now-stale ``AnimationManager`` view dropped via ``forget()``.
    """
    cell_size = mapper.cell_size
    current_ids: set = set()

    for row_index, row in enumerate(board_rows):
        for col_index, token in enumerate(row.split()):
            if token == ".":
                continue
            piece_id = f"{row_index},{col_index}"
            current_ids.add(piece_id)

            frame = animations.get_frame(piece_id, token)
            scaled = Img()
            scaled.img = cv2.resize(frame.img, (cell_size, cell_size), interpolation=cv2.INTER_AREA)
            x, y = mapper.cell_to_pixel(row_index, col_index)
            scaled.draw_on(screen, x, y)

    for stale_id in previous_ids - current_ids:
        animations.forget(stale_id)

    return current_ids


def _draw_selection(screen: Img, selection: Optional[Cell], mapper: BoardMapper) -> None:
    if selection is None:
        return
    cell_size = mapper.cell_size
    x, y = mapper.cell_to_pixel(selection.row, selection.col)
    cv2.rectangle(screen.img, (x, y), (x + cell_size - 1, y + cell_size - 1), SELECTED_BORDER_BGRA, 3)


def _draw_hud(screen: Img, coordinator: OnlineCoordinator, error_message: str) -> None:
    room_text = f"Room: {coordinator.room_id}" if coordinator.room_id else ""
    screen.put_text(room_text, 10, 20, font_size=0.5, color=HUD_TEXT_WHITE)

    if error_message:
        height = screen.img.shape[0]
        screen.put_text(error_message, 10, height - 15, font_size=0.5, color=HUD_TEXT_ERROR_BGRA)


def _draw_game_over(screen: Img, winner: Optional[str]) -> None:
    overlay = np.full(screen.img.shape, (*GAME_OVER_OVERLAY_BGR, 160), dtype=np.uint8)
    overlay_img = Img()
    overlay_img.img = overlay
    overlay_img.draw_on(screen, 0, 0)

    if winner is None:
        text = "Draw!"
    else:
        text = f"{'White' if winner == 'w' else 'Black'} wins!"
    width = screen.img.shape[1]
    screen.put_text(text, max(10, width // 2 - 80), screen.img.shape[0] // 2, font_size=0.9, color=GAME_OVER_TEXT_WHITE, thickness=2)
    screen.put_text(
        "Press any key to return to the Lobby",
        max(10, width // 2 - 140), screen.img.shape[0] // 2 + 40, font_size=0.5, color=GAME_OVER_TEXT_WHITE,
    )
