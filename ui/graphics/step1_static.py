import pathlib

from img import Img

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BOARD_PATH = REPO_ROOT / "board.png"
PIECE_PATH = REPO_ROOT / "pieces1" / "BB" / "states" / "idle" / "sprites" / "1.png"

PIECE_X = 50
PIECE_Y = 50


def main():
    board = Img().read(BOARD_PATH)
    piece = Img().read(PIECE_PATH)

    piece.draw_on(board, PIECE_X, PIECE_Y)
    board.show()


if __name__ == "__main__":
    main()
