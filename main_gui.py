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
from game_over_animation import GameOverAnimation
from graphics_board_renderer import GraphicsBoardRenderer
from img import Img

from core.config import VALID_PIECE_CHARS
from core.models import Color
from engine.board import AbstractBoard, TextBoard
from engine.board_validator import BoardValidationError, BoardValidator
from engine.game import GameEngine
from engine.game_state import GameState
from engine.move_history_tracker import MoveHistoryTracker
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
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help=(
            "Scale factor applied to the default cell size (the size "
            "main() would otherwise derive from board.png's own pixel "
            "dimensions). Ignored if --cell-size is also given. Default: 1.0."
        ),
    )
    parser.add_argument(
        "--cell-size",
        type=int,
        default=None,
        help=(
            "Exact pixel size of one board cell. Wins over --scale if "
            "both are given (a warning is logged noting --scale was "
            "ignored). Default: derived from board.png."
        ),
    )
    return parser.parse_args()


def _resolve_cell_size(args: argparse.Namespace, default_cell_size: int) -> int:
    """Return the cell size (px) to render at, per --cell-size/--scale.

    --cell-size wins outright when given — --scale is ignored, with a
    warning logged iff a non-default --scale was also given (so silently
    dropping it isn't a total surprise). Otherwise, --scale multiplies
    *default_cell_size*.
    """
    if args.cell_size is not None:
        if args.scale != 1.0:
            logger.warning(
                "Both --cell-size (%d) and --scale (%.3g) were given; "
                "--cell-size wins and --scale is ignored.",
                args.cell_size,
                args.scale,
            )
        return args.cell_size
    return round(default_cell_size * args.scale)


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

    board = _load_board(args.board)

    native_shape = Img().read(BOARD_PATH).img.shape
    native_height_px, native_width_px = native_shape[0], native_shape[1]
    default_cell_size = BoardMapper.from_board_pixels(
        native_width_px, native_height_px, board.num_cols, board.num_rows
    ).cell_size
    cell_size = _resolve_cell_size(args, default_cell_size)

    mapper = BoardMapper(cell_size)
    board_size = (cell_size * board.num_cols, cell_size * board.num_rows)

    engine = GameEngine(board, mapper=mapper)
    state = GameState(board=board)

    asset_loader = AssetLoader(PIECES_ROOT)
    renderer = GraphicsBoardRenderer(
        asset_loader, mapper, board_size=board_size, show_history_panel=True
    )
    score_tracker = ScoreTracker()
    history_tracker = MoveHistoryTracker()
    game_over_animation = GameOverAnimation()

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
        history_tracker.update(snapshot)
        game_over_animation.sync(snapshot)

        renderer.render(snapshot, screen, selected=engine.selection)
        renderer.render_scores(
            screen,
            score_tracker.get_score(Color.WHITE),
            score_tracker.get_score(Color.BLACK),
        )
        renderer.render_move_history(screen, history_tracker.moves)
        renderer.render_game_over(screen, snapshot.winner, game_over_animation.progress())

        # Img.show() blocks on cv2.waitKey(0) and tears the window down
        # right after — incompatible with a continuous render loop, so this
        # polls cv2 directly instead, same as the rest of this pipeline.
        cv2.imshow(WINDOW_NAME, screen.img)
        key = cv2.waitKey(30)
        # Unlike before this feature, game_over no longer breaks the loop
        # by itself -- the whole point of an animated, persistent
        # game-over screen is that it keeps rendering (and the window
        # stays open) after the game ends, until the user closes it
        # with ESC.
        if key == ESC:
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
