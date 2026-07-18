import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
GRAPHICS_DIR = REPO_ROOT / "ui" / "graphics"
# asset_loader.py / img.py / graphics_board_renderer.py import each other as
# flat sibling modules (e.g. `from img import Img`), which only resolves if
# their own directory is on sys.path.
sys.path.insert(0, str(GRAPHICS_DIR))

import argparse
import logging
import time

import cv2

from asset_loader import AssetLoader
from graphics_board_renderer import GraphicsBoardRenderer
from img import Img

from core.config import VALID_PIECE_CHARS
from core.models import Color
from engine.board import AbstractBoard, TextBoard
from engine.board_validator import BoardValidationError, BoardValidator
from engine.game import GameEngine
from engine.game_state import GameState
from engine.score_tracker import ScoreTracker
from engine.snapshot import GameSnapshot
from input.board_mapper import BoardMapper
from input.board_parser import BoardParser
from logger_config import setup_logging

logger = logging.getLogger(__name__)

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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kung Fu Chess GUI")
    parser.add_argument(
        "--board",
        type=pathlib.Path,
        default=None,
        help=(
            "Path to a text file with a custom starting board layout "
            "(same row format as STANDARD_BOARD_ROWS). Falls back to the "
            "standard layout if omitted, unreadable, or invalid."
        ),
    )
    return parser.parse_args()


def _load_board(board_path: "pathlib.Path | None") -> AbstractBoard:
    """Return the board to start the game with.

    Parses and validates *board_path* via the same ``BoardParser`` /
    ``BoardValidator`` pair ``main.py`` uses for the CLI pipeline — no
    second parser. Falls back to ``STANDARD_BOARD_ROWS`` (with a logged
    warning) if *board_path* is ``None``, unreadable, or fails
    validation; never raises.
    """
    if board_path is None:
        return TextBoard(STANDARD_BOARD_ROWS)

    try:
        with open(board_path, "r") as f:
            lines = f.readlines()
        board = BoardParser().parse(lines)
        BoardValidator(valid_chars=VALID_PIECE_CHARS).validate(board.get_rows())
        return board
    except (OSError, BoardValidationError) as e:
        logger.warning(
            "Failed to load board from %s (%s) — falling back to the standard starting layout.",
            board_path,
            e,
        )
        return TextBoard(STANDARD_BOARD_ROWS)


def main():
    setup_logging()
    args = _parse_args()

    board_shape = Img().read(BOARD_PATH).img.shape
    board_height_px, board_width_px = board_shape[0], board_shape[1]

    board = _load_board(args.board)
    mapper = BoardMapper.from_board_pixels(
        board_width_px, board_height_px, board.num_cols, board.num_rows
    )

    engine = GameEngine(board, mapper=mapper)
    state = GameState(board=board)

    asset_loader = AssetLoader(PIECES_ROOT)
    renderer = GraphicsBoardRenderer(asset_loader, mapper)
    score_tracker = ScoreTracker()

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

        snapshot = GameSnapshot.from_state(state)
        score_tracker.update(snapshot)

        renderer.render(snapshot, screen, selected=engine.selection)
        renderer.render_scores(
            screen,
            score_tracker.get_score(Color.WHITE),
            score_tracker.get_score(Color.BLACK),
        )

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
