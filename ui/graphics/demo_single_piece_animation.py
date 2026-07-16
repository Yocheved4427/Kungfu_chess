import time

import cv2

from asset_loader import AssetLoader
from demo_utils import draw_piece_on_copy
from img import Img
from paths import REPO_ROOT

ASSETS_BASE = REPO_ROOT / "assets"
BOARD_PATH = ASSETS_BASE / "board.png"
ASSETS_ROOT = ASSETS_BASE / "pieces2"
PIECE_CODE = "BB"
STATE_NAME = "idle"

PIECE_X = 50
PIECE_Y = 50
DURATION_SEC = 5.0


def main():
    loader = AssetLoader(ASSETS_ROOT)
    states = loader.load(PIECE_CODE)
    idle = states[STATE_NAME]

    board = Img().read(BOARD_PATH)

    start = time.time()
    while time.time() - start < DURATION_SEC:
        elapsed = time.time() - start
        piece_frame = idle.get_frame(elapsed)
        canvas = draw_piece_on_copy(board, piece_frame, PIECE_X, PIECE_Y)

        cv2.imshow("Kung Fu Chess", canvas.img)
        if cv2.waitKey(30) != -1:
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
