from __future__ import annotations

import argparse
import pathlib
import time

import cv2

from shared.logger_config import setup_logging
from shared.models.color import Color
from controllers.click_controller import ClickController
from engine.game import GameEngine
from engine.game_state import GameState
from engine.move_history_tracker import MoveHistoryTracker
from engine.score_tracker import ScoreTracker
from engine.snapshot import GameSnapshot
from input.board_mapper import BoardMapper
from src.rendering.game_over_animation import GameOverAnimation
from src.rendering.img import Img
from src.rendering.input_handler import InputHandler
from src.rendering.paths import REPO_ROOT
from src.rendering.renderer import BOARD_MARGIN_PX, SIDE_PANEL_WIDTH_PX, GraphicsBoardRenderer
from src.utils.asset_manager import AssetLoader
from ui.cli import _resolve_cell_size
from ui.game_factory import _load_board, _new_game

# ---------------------------------------------------------------------------
# Kung Fu Chess -- local desktop game entry point (src/main.py)
# ---------------------------------------------------------------------------
# Clean, LOCAL-ONLY entry point: single-player (hot-seat) or split-screen
# two-player, both on one machine, no server/account system involved.
# Deliberately excludes everything main_gui.py's hybrid loop also
# supports: --username networked play (network_client.py,
# server/server.py) and the login/dashboard account gate
# (login_view.py/dashboard_view.py, backed by server/database/). Use
# main_gui.py directly for either of those -- this file is not a
# replacement for it, just the clean local-play path split out on its
# own, per Server_Design.md's "local/two-player and the older WebSocket
# demo path" carve-out.
#
# Reuses rather than re-implements: ui.game_factory._new_game/_load_board
# (board/engine construction, unchanged, shared with main_gui.py) and
# ui.cli._resolve_cell_size (pure --cell-size/--scale arithmetic) --
# both stay at their existing repo-root path, imported here rather than
# duplicated.
# ---------------------------------------------------------------------------

WINDOW_NAME = "Kung Fu Chess"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kung Fu Chess -- local desktop game")
    parser.add_argument(
        "--board",
        type=pathlib.Path,
        default=None,
        help="Path to a text file with a custom starting board layout. "
        "Falls back to the standard layout if omitted, unreadable, or invalid.",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Scale factor applied to the default cell size. Ignored if --cell-size is given.",
    )
    parser.add_argument(
        "--cell-size",
        type=int,
        default=None,
        help="Exact pixel size of one board cell. Wins over --scale if both are given.",
    )
    parser.add_argument(
        "--two-player",
        action="store_true",
        help="Split-screen two-player mode instead of the single-window default.",
    )
    return parser.parse_args()


class _OwnColorClickController:
    """A ``ClickController`` restricted to selecting/moving pieces of one
    ``Color`` — two-player mode's per-half input handling.

    Two-player mode can't route both halves' clicks through
    ``GameEngine.handle_click``/``engine.selection`` directly:
    ``GameEngine`` always delegates to one internal ``ClickController``,
    so both halves would share a single ``selection``. Two independent
    ``ClickController`` instances, both wrapping the SAME ``GameEngine``/
    ``GameState`` (its methods are stateless, taking ``state``
    explicitly, so this is safe), each with their own ``selection``,
    fixes that — this class adds the other missing piece: restricting
    each instance to one player's own colour.
    """

    def __init__(self, engine: GameEngine, mapper: BoardMapper, own_color: Color) -> None:
        self._controller = ClickController(engine, mapper)
        self._mapper = mapper
        self._own_color = own_color

    @property
    def selection(self):
        return self._controller.selection

    def handle_click(self, state: GameState, x: int, y: int) -> None:
        if self._controller.selection is None:
            pos = self._mapper.pixel_to_cell(x, y)
            if state.board.contains(pos):
                piece = state.board.get_piece_at(pos)
                if piece is not None and piece != "." and piece[0] != self._own_color.value:
                    return  # not this player's piece -- ignore, don't even try to select
        self._controller.handle_click(state, x, y)


def _route_click(
    x: int,
    y: int,
    left_width: int,
    left_controller: _OwnColorClickController,
    right_controller: _OwnColorClickController,
    state: GameState,
) -> None:
    """Route a raw click at window pixel (*x*, *y*) to whichever half
    owns that region, translating *x* into that half's own local
    coordinate space first."""
    if x < left_width:
        left_controller.handle_click(state, x, y)
    else:
        right_controller.handle_click(state, x - left_width, y)


def _hstack(left: Img, right: Img) -> Img:
    """Compose *left* and *right* side by side into one new ``Img`` --
    both must already be the same height."""
    combined = Img()
    combined.img = cv2.hconcat([left.img, right.img])
    return combined


def _run_single_player(
    args: argparse.Namespace,
    mapper: BoardMapper,
    board_size: "tuple[int, int]",
    asset_loader: AssetLoader,
    screen: Img,
    input_handler: InputHandler,
) -> None:
    """The single-window, single-mouse-stream game loop."""
    quit_requested = False
    while not quit_requested:
        # Every per-game object is rebuilt fresh here, for the first game
        # and every restart alike -- see _new_game's own docstring for
        # why GameEngine specifically can't just be reused.
        engine, state = _new_game(args, mapper)
        renderer = GraphicsBoardRenderer(
            asset_loader, mapper, board_size=board_size, show_side_panels=True
        )
        score_tracker = ScoreTracker()
        history_tracker = MoveHistoryTracker()
        game_over_animation = GameOverAnimation()

        restart_requested = False
        last_time = time.time()

        while not restart_requested and not quit_requested:
            now = time.time()
            elapsed_ms = int((now - last_time) * 1000)
            last_time = now

            engine.tick(state, elapsed_ms)

            for x, y in input_handler.poll_clicks():
                engine.handle_click(state, x, y)

            snapshot = GameSnapshot.from_state(state)
            score_tracker.update(snapshot)
            history_tracker.update(snapshot)
            game_over_animation.sync(snapshot)

            renderer.render(snapshot, screen, selected=engine.selection)
            renderer.render_player_panel(
                screen, Color.WHITE, score_tracker.get_score(Color.WHITE), history_tracker.moves,
            )
            renderer.render_player_panel(
                screen, Color.BLACK, score_tracker.get_score(Color.BLACK), history_tracker.moves,
            )
            renderer.render_game_over(screen, snapshot.winner, game_over_animation.progress())

            cv2.imshow(WINDOW_NAME, screen.img)
            key = input_handler.poll_key(30)

            if InputHandler.is_quit(key, snapshot.game_over):
                quit_requested = True
            elif InputHandler.is_restart(key, snapshot.game_over):
                restart_requested = True


def _run_two_player(
    args: argparse.Namespace,
    mapper: BoardMapper,
    board_size: "tuple[int, int]",
    asset_loader: AssetLoader,
    screen: Img,
    input_handler: InputHandler,
    white_username: str = "White",
    black_username: str = "Black",
) -> None:
    """Split-screen two-player loop: White plays the left half, Black
    the right — one shared ``GameEngine``/``GameState`` (it's one game),
    but everything about presenting and controlling it is duplicated per
    half. See ``_OwnColorClickController``/``_route_click`` for why a
    shared ``GameEngine.handle_click``/``engine.selection`` can't be
    used directly here.
    """
    left_width = board_size[0]

    quit_requested = False
    while not quit_requested:
        engine, state = _new_game(args, mapper)
        left_renderer = GraphicsBoardRenderer(asset_loader, mapper, board_size=board_size)
        right_renderer = GraphicsBoardRenderer(
            asset_loader, mapper, board_size=board_size, show_history_panel=True
        )
        left_controller = _OwnColorClickController(engine, mapper, Color.WHITE)
        right_controller = _OwnColorClickController(engine, mapper, Color.BLACK)

        score_tracker = ScoreTracker()
        history_tracker = MoveHistoryTracker()
        game_over_animation = GameOverAnimation()

        restart_requested = False
        last_time = time.time()

        while not restart_requested and not quit_requested:
            now = time.time()
            elapsed_ms = int((now - last_time) * 1000)
            last_time = now

            engine.tick(state, elapsed_ms)

            for x, y in input_handler.poll_clicks():
                _route_click(x, y, left_width, left_controller, right_controller, state)

            snapshot = GameSnapshot.from_state(state)
            score_tracker.update(snapshot)
            history_tracker.update(snapshot)
            game_over_animation.sync(snapshot)

            white_score = score_tracker.get_score(Color.WHITE)
            black_score = score_tracker.get_score(Color.BLACK)

            left_screen = Img()
            left_renderer.render(snapshot, left_screen, selected=left_controller.selection)
            left_renderer.render_scores(
                left_screen, white_score, black_score, white_username, black_username
            )

            right_screen = Img()
            right_renderer.render(snapshot, right_screen, selected=right_controller.selection)
            right_renderer.render_scores(
                right_screen, white_score, black_score, white_username, black_username
            )
            right_renderer.render_move_history(right_screen, history_tracker.moves)

            combined = _hstack(left_screen, right_screen)
            right_renderer.render_game_over(combined, snapshot.winner, game_over_animation.progress())
            screen.img = combined.img

            cv2.imshow(WINDOW_NAME, screen.img)
            key = input_handler.poll_key(30)

            if InputHandler.is_quit(key, snapshot.game_over):
                quit_requested = True
            elif InputHandler.is_restart(key, snapshot.game_over):
                restart_requested = True


def main() -> None:
    setup_logging()
    args = _parse_args()

    probe_board = _load_board(args.board)
    native_shape = Img().read(BOARD_IMAGE_PATH).img.shape
    native_height_px, native_width_px = native_shape[0], native_shape[1]
    default_cell_size = BoardMapper.from_board_pixels(
        native_width_px, native_height_px, probe_board.num_cols, probe_board.num_rows
    ).cell_size
    cell_size = _resolve_cell_size(args, default_cell_size)
    board_size = (cell_size * probe_board.num_cols, cell_size * probe_board.num_rows)
    asset_loader = AssetLoader(PIECES_ROOT)

    two_player_mapper = BoardMapper(cell_size)
    single_player_mapper = BoardMapper(
        cell_size,
        x_offset=2 * BOARD_MARGIN_PX + SIDE_PANEL_WIDTH_PX,
        y_offset=BOARD_MARGIN_PX,
    )

    cv2.namedWindow(WINDOW_NAME)
    input_handler = InputHandler(WINDOW_NAME)
    screen = Img()

    if args.two_player:
        _run_two_player(args, two_player_mapper, board_size, asset_loader, screen, input_handler)
    else:
        _run_single_player(args, single_player_mapper, board_size, asset_loader, screen, input_handler)

    cv2.destroyAllWindows()


ASSETS_ROOT = REPO_ROOT / "assets"
BOARD_IMAGE_PATH = ASSETS_ROOT / "board.png"
PIECES_ROOT = ASSETS_ROOT / "pieces3"


if __name__ == "__main__":
    main()
