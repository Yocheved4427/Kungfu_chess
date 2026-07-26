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

from dashboard_view import run_dashboard_screen
from input.board_mapper import BoardMapper
from logger_config import setup_logging
from login_view import run_login_screen
from ui.cli import _parse_args, _resolve_cell_size
from ui.game_factory import _load_board
from ui.game_loop import WINDOW_NAME, _run_single_player, _run_two_player

logger = logging.getLogger(__name__)

ASSETS_ROOT = REPO_ROOT / "assets"
BOARD_PATH = ASSETS_ROOT / "board.png"
PIECES_ROOT = ASSETS_ROOT / "pieces3"


def _login_and_confirm(prompt: str, exclude_user_id: "int | None" = None) -> "dict | None":
    """Log a player in, show their dashboard, and keep looping back to a
    fresh login if they log out from it — the one place both
    login_view.py and dashboard_view.py's window lifecycles are
    sequenced, so main() itself stays a plain "call this, get a user or
    None back" composition.

    Returns the confirmed user profile (dashboard's "Start New Game")
    once ready to play, or None if the player cancelled (Esc) at either
    the login or the dashboard screen — main() treats both identically:
    abort startup, no game window ever opens.
    """
    while True:
        user = run_login_screen(prompt=prompt, exclude_user_id=exclude_user_id)
        if user is None:
            return None

        action = run_dashboard_screen(user)
        if action == "start":
            return user
        if action is None:
            return None
        # action == "logout" -- loop back to a fresh login screen.


def main():
    setup_logging()
    args = _parse_args()

    # Login + dashboard gate: the game itself (GameEngine, AssetLoader,
    # the board window) is only ever initialized below this point, and
    # only once every required player has logged in AND confirmed
    # "Start New Game" from their own dashboard -- see login_view.py's
    # and dashboard_view.py's own module docstrings for why these are
    # separate cv2 windows rather than a second GUI toolkit.
    # --two-player needs one login+dashboard pass per side (White, then
    # Black); Black is barred from logging in as the same account White
    # just used (exclude_user_id) so game_history's white_player_id/
    # black_player_id can never both point at one user. Cancelling any
    # login or dashboard (Esc) aborts startup entirely.
    if args.two_player:
        white_user = _login_and_confirm(prompt="White: log in or register")
        if white_user is None:
            logger.info("Login cancelled -- exiting")
            return
        black_user = _login_and_confirm(
            prompt="Black: log in or register", exclude_user_id=white_user["user_id"]
        )
        if black_user is None:
            logger.info("Login cancelled -- exiting")
            return
        logger.info(
            "Starting two-player game: white=%r black=%r",
            white_user["username"], black_user["username"],
        )
    else:
        player_user = _login_and_confirm(prompt="Log in or register to play")
        if player_user is None:
            logger.info("Login cancelled -- exiting")
            return
        logger.info("Starting single-player session for %r", player_user["username"])

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
        _run_two_player(
            args, two_player_mapper, board_size, asset_loader, screen, pending_clicks,
            white_username=white_user["username"], black_username=black_user["username"],
        )
    else:
        _run_single_player(
            args, single_player_mapper, board_size, asset_loader, screen, pending_clicks
        )

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
