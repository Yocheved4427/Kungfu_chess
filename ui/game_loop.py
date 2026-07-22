from __future__ import annotations

import argparse
import time

import cv2

from asset_loader import AssetLoader
from game_over_animation import GameOverAnimation
from graphics_board_renderer import GraphicsBoardRenderer
from img import Img

from controllers.click_controller import ClickController
from core.models import Color, Position
from engine.game import GameEngine
from engine.game_state import GameState
from engine.move_history_tracker import MoveHistoryTracker
from engine.score_tracker import ScoreTracker
from engine.snapshot import GameSnapshot
from input.board_mapper import BoardMapper
from ui.game_factory import _new_game

WINDOW_NAME = "Kung Fu Chess"
ESC = 27


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
