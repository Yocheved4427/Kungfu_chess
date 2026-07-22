import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
GRAPHICS_DIR = REPO_ROOT / "ui" / "graphics"
# asset_loader.py / img.py / graphics_board_renderer.py import each other as
# flat sibling modules (e.g. `from img import Img`), which only resolves if
# their own directory is on sys.path.
sys.path.insert(0, str(GRAPHICS_DIR))

import logging

import cv2

from asset_loader import AssetLoader
from graphics_board_renderer import BOARD_MARGIN_PX, SIDE_PANEL_WIDTH_PX
from img import Img

from input.board_mapper import BoardMapper
from logger_config import setup_logging
from ui.cli import _parse_args, _resolve_cell_size
from ui.game_factory import _load_board
from ui.game_loop import WINDOW_NAME, _run_single_player, _run_two_player

logger = logging.getLogger(__name__)

ASSETS_ROOT = REPO_ROOT / "assets"
BOARD_PATH = ASSETS_ROOT / "board.png"
PIECES_ROOT = ASSETS_ROOT / "pieces3"


def main():
    setup_logging()
    args = _parse_args()

    # Launch-config-derived setup: fixed for the process's whole lifetime,
    # unaffected by restarts (a restart rebuilds the game itself, not how
    # it's launched) -- board_size, in particular, comes from a one-time
    # board read purely to size things, independent of whichever TextBoard
    # instance actually ends up played on in a given game.
    probe_board = _load_board(args.board)
    native_shape = Img().read(BOARD_PATH).img.shape
    native_height_px, native_width_px = native_shape[0], native_shape[1]
    default_cell_size = BoardMapper.from_board_pixels(
        native_width_px, native_height_px, probe_board.num_cols, probe_board.num_rows
    ).cell_size
    cell_size = _resolve_cell_size(args, default_cell_size)
    board_size = (cell_size * probe_board.num_cols, cell_size * probe_board.num_rows)
    asset_loader = AssetLoader(PIECES_ROOT)  # sprite cache: reused across restarts

    # Two different mappers for two different layouts sharing one cell_size:
    # two-player mode's two halves each draw their own board starting at
    # local (0, 0) (unchanged from before this task -- see _run_two_player),
    # while single-player mode now draws the board offset within a wider
    # canvas that also has side panels (see GraphicsBoardRenderer's
    # show_side_panels and render_player_panel) -- its mapper must agree,
    # per BoardMapper's own docstring on x_offset/y_offset.
    two_player_mapper = BoardMapper(cell_size)
    single_player_mapper = BoardMapper(
        cell_size,
        x_offset=2 * BOARD_MARGIN_PX + SIDE_PANEL_WIDTH_PX,
        y_offset=BOARD_MARGIN_PX,
    )

    pending_clicks = []

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            pending_clicks.append((x, y))

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, on_mouse)

    screen = Img()

    if args.two_player:
        _run_two_player(args, two_player_mapper, board_size, asset_loader, screen, pending_clicks)
    else:
        _run_single_player(
            args, single_player_mapper, board_size, asset_loader, screen, pending_clicks
        )

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
