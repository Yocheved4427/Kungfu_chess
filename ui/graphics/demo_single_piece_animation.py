import os
import pathlib
import time

import cv2

from asset_loader import AssetLoader
from img import Img

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BOARD_PATH = REPO_ROOT / "board.png"
ASSETS_ROOT = REPO_ROOT / "pieces2"
PIECE_CODE = "BB"
STATE_NAME = "idle"

PIECE_X = 50
PIECE_Y = 50
DURATION_SEC = 5.0


def frame_at(board: Img, sequence, elapsed_sec: float) -> Img:
    canvas = Img()
    canvas.img = board.img.copy()

    piece = sequence.get_frame(elapsed_sec)
    piece.draw_on(canvas, PIECE_X, PIECE_Y)

    return canvas


def main():
    loader = AssetLoader(ASSETS_ROOT)
    states = loader.load(PIECE_CODE)
    idle = states[STATE_NAME]

    # cv2.imread cannot open absolute paths containing non-ASCII characters
    # on Windows, so read relative to the working directory.
    board = Img().read(os.path.relpath(BOARD_PATH, start=os.getcwd()))

    start = time.time()
    while time.time() - start < DURATION_SEC:
        elapsed = time.time() - start
        canvas = frame_at(board, idle, elapsed)

        cv2.imshow("Kung Fu Chess", canvas.img)
        if cv2.waitKey(30) != -1:
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
