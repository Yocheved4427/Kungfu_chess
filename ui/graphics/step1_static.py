import os
import pathlib

from img import Img

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ASSETS_ROOT = REPO_ROOT / "assets"
BOARD_PATH = ASSETS_ROOT / "board.png"
PIECE_PATH = ASSETS_ROOT / "pieces1" / "BB" / "states" / "idle" / "sprites" / "1.png"

PIECE_X = 50
PIECE_Y = 50


def main():
    # cv2.imread cannot open absolute paths containing non-ASCII characters
    # on Windows, so read relative to the working directory.
    board = Img().read(os.path.relpath(BOARD_PATH, start=os.getcwd()))
    piece = Img().read(os.path.relpath(PIECE_PATH, start=os.getcwd()))

    piece.draw_on(board, PIECE_X, PIECE_Y)
    board.show()


if __name__ == "__main__":
    main()
