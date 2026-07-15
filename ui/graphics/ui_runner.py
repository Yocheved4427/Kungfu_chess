import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
# This script's own directory (ui/graphics) is what Python puts on
# sys.path when run directly — the repo root needs adding explicitly so
# `core.*` / `engine.*` / `input.*` package imports below can resolve.
sys.path.insert(0, str(REPO_ROOT))

import os
import time

import cv2

from asset_loader import AssetLoader
from graphics_board_renderer import GraphicsBoardRenderer
from img import Img

from core.models import Position
from engine.board import TextBoard
from engine.game import GameEngine
from engine.game_state import GameState
from input.board_mapper import BoardMapper

BOARD_PATH = REPO_ROOT / "board.png"
ASSETS_ROOT = REPO_ROOT / "pieces2"

STANDARD_BOARD_ROWS = [
    "bR bN bB bQ bK bB bN bR",
    "bP bP bP bP bP bP bP bP",
    ". . . . . . . .",
    ". . . . . . . .",
    ". . . . . . . .",
    ". . . . . . . .",
    "wP wP wP wP wP wP wP wP",
    "wR wN wB wQ wK wB wN wR",
]

WINDOW_NAME = "Kung Fu Chess"
ESC = 27


def main():
    # cv2.imread cannot open absolute paths containing non-ASCII characters
    # on Windows, so read relative to the working directory.
    board_shape = Img().read(os.path.relpath(BOARD_PATH, start=os.getcwd())).img.shape
    board_height_px, board_width_px = board_shape[0], board_shape[1]

    board = TextBoard(STANDARD_BOARD_ROWS)
    # One shared BoardMapper for both rendering and click handling, so
    # they can never disagree on cell size.
    mapper = BoardMapper.from_board_pixels(
        board_width_px, board_height_px, board.num_cols, board.num_rows
    )

    engine = GameEngine(board, mapper=mapper)
    state = GameState(board=board)

    asset_loader = AssetLoader(ASSETS_ROOT)
    renderer = GraphicsBoardRenderer(asset_loader, mapper)

    pending_clicks = []

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            pending_clicks.append((x, y))

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, on_mouse)

    window_img = Img()
    last_time = time.time()

    while True:
        now = time.time()
        elapsed_ms = int((now - last_time) * 1000)
        last_time = now

        engine.tick(state, elapsed_ms)

        for x, y in pending_clicks:
            engine.handle_click(state, x, y)
        pending_clicks.clear()

        renderer.render(state, window_img)
        cv2.imshow(WINDOW_NAME, window_img.img)

        key = cv2.waitKey(30)
        if key == ESC or state.game_over:
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
