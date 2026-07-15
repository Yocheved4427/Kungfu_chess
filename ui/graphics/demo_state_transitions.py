import os
import pathlib

import cv2

from asset_loader import AssetLoader
from img import Img
from piece_state_machine import PieceStateMachine

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BOARD_PATH = REPO_ROOT / "board.png"
ASSETS_ROOT = REPO_ROOT / "pieces2"
PIECE_CODE = "BB"

PIECE_X = 50
PIECE_Y = 50

SPACEBAR = ord(" ")
ESC = 27
MAX_RUNTIME_MS = 60_000


def frame_at(board: Img, piece_frame: Img) -> Img:
    canvas = Img()
    canvas.img = board.img.copy()
    piece_frame.draw_on(canvas, PIECE_X, PIECE_Y)
    return canvas


def main():
    loader = AssetLoader(ASSETS_ROOT)
    states = loader.load(PIECE_CODE)
    machine = PieceStateMachine(states, start_state="idle")

    # cv2.imread cannot open absolute paths containing non-ASCII characters
    # on Windows, so read relative to the working directory.
    board = Img().read(os.path.relpath(BOARD_PATH, start=os.getcwd()))

    last_state = machine.current_state
    print(f"state: {last_state}")

    elapsed_ms = 0
    while elapsed_ms < MAX_RUNTIME_MS:
        piece_frame = machine.get_current_frame()

        if machine.current_state != last_state:
            last_state = machine.current_state
            print(f"state: {last_state}")

        canvas = frame_at(board, piece_frame)
        cv2.imshow("Kung Fu Chess", canvas.img)

        key = cv2.waitKey(30)
        elapsed_ms += 30

        if key == SPACEBAR:
            # pieces2's config marks only "jump" as is_loop: false, so it's
            # the state that actually demonstrates an auto-return chain
            # (jump -> short_rest). short_rest itself is is_loop: true in
            # this asset set, so it won't auto-advance further into idle.
            machine.transition_to("jump")
        elif key == ESC:
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
