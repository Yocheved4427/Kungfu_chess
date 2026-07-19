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
from graphics_board_renderer import BOARD_MARGIN_PX, SIDE_PANEL_WIDTH_PX, GraphicsBoardRenderer
from img import Img

from controllers.click_controller import ClickController
from core.config import VALID_PIECE_CHARS
from core.models import Color, Position
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
    parser.add_argument(
        "--two-player",
        action="store_true",
        help=(
            "Split-screen two-player mode: White plays the left half, "
            "Black the right half, each with independent click/selection "
            "state and restricted to their own colour. Single-player "
            "mode (the default) is unchanged."
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


def _new_game(args: argparse.Namespace, mapper: BoardMapper) -> "tuple[GameEngine, GameState]":
    """Build a fresh ``GameEngine`` + ``GameState`` pair from *args*' launch
    settings (the same ``--board`` source ``_load_board`` used at startup)
    and the already-resolved *mapper*.

    Used both for the very first game and every restart. A restart can't
    just build a new ``GameState`` and keep the existing ``GameEngine``:
    ``GameEngine``'s default ``GameOverRule`` (``KingCaptureRule``) is
    stateful and explicitly documented as scoped to a single game — see
    that class's own docstring: "don't share a ``KingCaptureRule`` across
    two ``GameEngine`` instances." Reusing one would carry over which
    colours it saw as "armed" (and already lost) from the previous game,
    so the new game could report itself over immediately. A fresh
    ``GameEngine`` (which primes a fresh ``KingCaptureRule`` from the
    fresh board at construction) avoids that entirely.
    """
    board = _load_board(args.board)
    engine = GameEngine(board, mapper=mapper)
    state = GameState(board=board)
    return engine, state


class _OwnColorClickController:
    """A ``ClickController`` restricted to selecting/moving pieces of one
    ``Color`` — two-player mode's per-half input handling.

    Two-player mode can't route both halves' clicks through
    ``GameEngine.handle_click``/``engine.selection`` directly:
    ``GameEngine`` always delegates to one internal ``ClickController``,
    so both halves would share a single ``selection``. A click on the
    right half while the left half already has a piece selected would
    then be read as "move the left half's selected piece to wherever the
    right half just clicked" — ``ClickController.handle_click``'s own
    "switch selection" rule only applies to a *same-colour* click,
    otherwise it's a move attempt (see that class's docstring). Two
    independent ``ClickController`` instances, both wrapping the SAME
    ``GameEngine``/``GameState`` (its methods are stateless, taking
    ``state`` explicitly, so this is safe), each with their own
    ``selection``, fixes that — this class adds the other missing piece:
    restricting each instance to one player's own colour.

    Only guard needed: refuse to SELECT a piece that isn't *own_color*.
    Once nothing else can ever become the held selection, every
    subsequent move-attempt click (which always acts on the CURRENT
    selection) naturally only ever moves an *own_color* piece too — no
    separate check is needed for that case.
    """

    def __init__(self, engine: GameEngine, mapper: BoardMapper, own_color: Color) -> None:
        self._controller = ClickController(engine, mapper)
        self._mapper = mapper
        self._own_color = own_color

    @property
    def selection(self) -> "Position | None":
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
    coordinate space first — each half's ``BoardMapper`` assumes its own
    board starts at local x=0, so the right half needs *left_width*
    subtracted before its own pixel<->cell math is correct.

    A click at ``x < left_width`` must only ever reach
    *left_controller*, and one at ``x >= left_width`` only ever
    *right_controller* — never both, never the wrong one.
    """
    if x < left_width:
        left_controller.handle_click(state, x, y)
    else:
        right_controller.handle_click(state, x - left_width, y)


def _hstack(left: Img, right: Img) -> Img:
    """Compose *left* and *right* side by side into one new ``Img`` —
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
    pending_clicks: list,
) -> None:
    """The single-window, single-mouse-stream game loop.

    *mapper* must already be constructed with the side-panel-aware
    ``x_offset``/``y_offset`` (see ``main()``) — this function itself
    just uses it via ``GraphicsBoardRenderer``/``ClickController``, same
    as every other caller, since ``BoardMapper`` is the one place that
    arithmetic belongs (see that class's own module docstring). Board,
    White's panel, and Black's panel are laid out by
    ``GraphicsBoardRenderer``'s own ``show_side_panels`` — see that
    class's docstring and ``render_player_panel``'s for the full layout
    and the bug (score text overlapping the board's own top-row pieces)
    this replaces.
    """
    quit_requested = False
    while not quit_requested:
        # Every per-game object is rebuilt fresh here, for the first game
        # and every restart alike -- see _new_game's own docstring for why
        # GameEngine specifically can't just be reused. renderer is rebuilt
        # too (fresh _piece_views, so no stale PieceView/animation state
        # carries over) but asset_loader/mapper aren't: neither holds any
        # per-game state, just already-loaded sprites and fixed geometry.
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

            for x, y in pending_clicks:
                engine.handle_click(state, x, y)
            pending_clicks.clear()

            snapshot = GameSnapshot.from_state(state)
            score_tracker.update(snapshot)
            history_tracker.update(snapshot)
            game_over_animation.sync(snapshot)

            renderer.render(snapshot, screen, selected=engine.selection)
            renderer.render_player_panel(
                screen,
                Color.WHITE,
                score_tracker.get_score(Color.WHITE),
                history_tracker.moves,
            )
            renderer.render_player_panel(
                screen,
                Color.BLACK,
                score_tracker.get_score(Color.BLACK),
                history_tracker.moves,
            )
            renderer.render_game_over(
                screen, snapshot.winner, game_over_animation.progress()
            )

            # Img.show() blocks on cv2.waitKey(0) and tears the window down
            # right after — incompatible with a continuous render loop, so
            # this polls cv2 directly instead, same as the rest of this
            # pipeline.
            cv2.imshow(WINDOW_NAME, screen.img)
            key = cv2.waitKey(30)

            if key == ESC:
                quit_requested = True
            elif snapshot.game_over and key in (ord("q"), ord("Q")):
                quit_requested = True
            elif snapshot.game_over and key in (ord("r"), ord("R")):
                restart_requested = True


def _run_two_player(
    args: argparse.Namespace,
    mapper: BoardMapper,
    board_size: "tuple[int, int]",
    asset_loader: AssetLoader,
    screen: Img,
    pending_clicks: list,
) -> None:
    """Split-screen two-player loop: White plays the left half, Black
    the right — one shared ``GameEngine``/``GameState`` (it's one game),
    but everything about presenting and controlling it is duplicated per
    half. See main_gui.py's design discussion (this function's sibling,
    ``_run_single_player``, and ``_OwnColorClickController``/
    ``_route_click``) for why a shared ``GameEngine.handle_click`` /
    ``engine.selection`` can't be used directly here.

    History panel is shown once, on the right half's own outer right
    edge (reusing ``show_history_panel`` unchanged); each half draws its
    own score overlay so neither player needs to look at the other half
    to check standings; the game-over screen is drawn once on the final
    composited canvas (``render_game_over`` depends only on its own
    arguments, not renderer instance state, so either renderer can call
    it — the right one is used here, arbitrarily).
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

            for x, y in pending_clicks:
                _route_click(x, y, left_width, left_controller, right_controller, state)
            pending_clicks.clear()

            snapshot = GameSnapshot.from_state(state)
            score_tracker.update(snapshot)
            history_tracker.update(snapshot)
            game_over_animation.sync(snapshot)

            white_score = score_tracker.get_score(Color.WHITE)
            black_score = score_tracker.get_score(Color.BLACK)

            left_screen = Img()
            left_renderer.render(snapshot, left_screen, selected=left_controller.selection)
            left_renderer.render_scores(left_screen, white_score, black_score)

            right_screen = Img()
            right_renderer.render(snapshot, right_screen, selected=right_controller.selection)
            right_renderer.render_scores(right_screen, white_score, black_score)
            right_renderer.render_move_history(right_screen, history_tracker.moves)

            combined = _hstack(left_screen, right_screen)
            right_renderer.render_game_over(
                combined, snapshot.winner, game_over_animation.progress()
            )
            screen.img = combined.img

            # Img.show() blocks on cv2.waitKey(0) and tears the window down
            # right after — incompatible with a continuous render loop, so
            # this polls cv2 directly instead, same as the rest of this
            # pipeline.
            cv2.imshow(WINDOW_NAME, screen.img)
            key = cv2.waitKey(30)

            if key == ESC:
                quit_requested = True
            elif snapshot.game_over and key in (ord("q"), ord("Q")):
                quit_requested = True
            elif snapshot.game_over and key in (ord("r"), ord("R")):
                restart_requested = True


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
