import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
GRAPHICS_DIR = REPO_ROOT / "ui" / "graphics"
# asset_loader.py / img.py / graphics_board_renderer.py import each other as
# flat sibling modules (e.g. `from img import Img`), which only resolves if
# their own directory is on sys.path.
sys.path.insert(0, str(GRAPHICS_DIR))

import time

import cv2

from asset_loader import AssetLoader
from graphics_board_renderer import GraphicsBoardRenderer
from img import Img

from engine.board import TextBoard
from engine.game import GameEngine
from engine.game_state import GameState
from input.board_mapper import BoardMapper

ASSETS_ROOT = REPO_ROOT / "assets"
BOARD_PATH = ASSETS_ROOT / "board.png"
PIECES_ROOT = ASSETS_ROOT / "pieces3"

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
    board_shape = Img().read(BOARD_PATH).img.shape
    board_height_px, board_width_px = board_shape[0], board_shape[1]

    board = TextBoard(STANDARD_BOARD_ROWS)
    mapper = BoardMapper.from_board_pixels(
        board_width_px, board_height_px, board.num_cols, board.num_rows
    )

    engine = GameEngine(board, mapper=mapper)
    state = GameState(board=board)

    asset_loader = AssetLoader(PIECES_ROOT)
    renderer = GraphicsBoardRenderer(asset_loader, mapper)

    pending_clicks = []

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            pending_clicks.append((x, y))

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, on_mouse)

    screen = Img()
    last_time = time.time()

    while True:
        now = time.time()
        elapsed_ms = int((now - last_time) * 1000)
        last_time = now

        engine.tick(state, elapsed_ms)

        for x, y in pending_clicks:
            engine.handle_click(state, x, y)
        pending_clicks.clear()

        renderer.render(state, screen)

        # Img.show() blocks on cv2.waitKey(0) and tears the window down
        # right after — incompatible with a continuous render loop, so this
        # polls cv2 directly instead, same as the rest of this pipeline.
        cv2.imshow(WINDOW_NAME, screen.img)
        key = cv2.waitKey(30)
        if key == ESC or state.game_over:
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
