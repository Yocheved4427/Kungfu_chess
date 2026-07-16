import cv2

from asset_loader import AssetLoader
from demo_utils import draw_piece_on_copy
from img import Img
from paths import REPO_ROOT
from piece_state_machine import PieceStateMachine

ASSETS_BASE = REPO_ROOT / "assets"
BOARD_PATH = ASSETS_BASE / "board.png"
ASSETS_ROOT = ASSETS_BASE / "pieces2"
PIECE_CODE = "BB"

PIECE_X = 50
PIECE_Y = 50

SPACEBAR = ord(" ")
ESC = 27
MAX_RUNTIME_MS = 60_000


def main():
    loader = AssetLoader(ASSETS_ROOT)
    states = loader.load(PIECE_CODE)
    machine = PieceStateMachine(states, start_state="idle")

    board = Img().read(BOARD_PATH)

    last_state = machine.current_state
    print(f"state: {last_state}")

    elapsed_ms = 0
    while elapsed_ms < MAX_RUNTIME_MS:
        piece_frame = machine.get_current_frame()

        if machine.current_state != last_state:
            last_state = machine.current_state
            print(f"state: {last_state}")

        canvas = draw_piece_on_copy(board, piece_frame, PIECE_X, PIECE_Y)
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
