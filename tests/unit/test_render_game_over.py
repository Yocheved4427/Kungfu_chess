"""
Unit tests for GraphicsBoardRenderer.render_game_over's visual output.

ui/graphics modules import each other as flat sibling modules, which only
resolves if ui/graphics itself is on sys.path — same setup as
test_piece_view.py (see that file's own header comment for why).

render_game_over takes an already-computed *progress* float (see
GameOverAnimation, tested separately in test_game_over_animation.py) —
so these tests drive it with fixed progress values directly rather than
advancing a real or fake clock, avoiding any dependency on wall-clock
timing (or on piece-sprite animation frames, which do depend on
wall-clock time since each PieceView's construction — an empty board is
used here specifically to keep that out of the picture entirely).
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np

GRAPHICS_DIR = pathlib.Path(__file__).resolve().parents[2] / "ui" / "graphics"
sys.path.insert(0, str(GRAPHICS_DIR))

from asset_loader import AssetLoader  # noqa: E402
from graphics_board_renderer import GraphicsBoardRenderer  # noqa: E402
from img import Img  # noqa: E402

from core.models import Color  # noqa: E402
from engine.board import TextBoard  # noqa: E402
from engine.game_state import GameState  # noqa: E402
from engine.snapshot import GameSnapshot  # noqa: E402
from input.board_mapper import BoardMapper  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PIECES_ROOT = REPO_ROOT / "assets" / "pieces3"
BOARD_PATH = REPO_ROOT / "assets" / "board.png"


def _renderer() -> GraphicsBoardRenderer:
    board_shape = Img().read(str(BOARD_PATH)).img.shape
    mapper = BoardMapper.from_board_pixels(board_shape[1], board_shape[0], 8, 8)
    return GraphicsBoardRenderer(AssetLoader(PIECES_ROOT), mapper)


def _rendered_empty_board() -> Img:
    renderer = _renderer()
    board = TextBoard([". . .", ". . .", ". . ."])
    state = GameState(board=board)
    screen = Img()
    renderer.render(GameSnapshot.from_state(state), screen)
    return renderer, screen


class TestVisualStateAtStartDiffersFromSettled:
    def test_t0_differs_from_the_settled_end_state(self):
        renderer, screen = _rendered_empty_board()
        plain_board = screen.img.copy()

        renderer.render_game_over(screen, Color.WHITE, progress=0.001)
        near_start = screen.img.copy()

        screen.img = plain_board.copy()
        renderer.render_game_over(screen, Color.WHITE, progress=1.0)
        settled = screen.img.copy()

        assert not np.array_equal(near_start, settled)

    def test_settled_overlay_is_more_opaque_than_near_the_start(self):
        """Not just "different somehow" -- specifically that the settled
        (progress=1.0) frame has visibly darkened the board more than
        the very start (progress~0) did, i.e. the overlay is actually
        fading IN, not some other unrelated change."""
        renderer, screen = _rendered_empty_board()
        plain_board = screen.img.copy()

        renderer.render_game_over(screen, Color.WHITE, progress=0.001)
        near_start = screen.img.copy()
        diff_near_start = np.abs(near_start.astype(int) - plain_board.astype(int)).sum()

        screen.img = plain_board.copy()
        renderer.render_game_over(screen, Color.WHITE, progress=1.0)
        settled = screen.img.copy()
        diff_settled = np.abs(settled.astype(int) - plain_board.astype(int)).sum()

        assert diff_settled > diff_near_start

    def test_progress_zero_draws_nothing(self):
        renderer, screen = _rendered_empty_board()
        before = screen.img.copy()

        renderer.render_game_over(screen, Color.WHITE, progress=0.0)

        assert np.array_equal(screen.img, before)


class TestSettledStateStaysVisibleIndefinitely:
    def test_progress_of_1_looks_the_same_no_matter_how_it_was_reached(self):
        """Once "settled" (progress clamped to 1.0, as GameOverAnimation
        guarantees once the fade duration has elapsed), the drawn frame
        must be identical every time -- nothing here should depend on
        how much *more* time has passed beyond settling, since
        render_game_over only ever sees the already-clamped progress
        value, never raw elapsed time itself."""
        renderer, screen = _rendered_empty_board()
        plain_board = screen.img.copy()

        renderer.render_game_over(screen, Color.WHITE, progress=1.0)
        first_settled = screen.img.copy()

        screen.img = plain_board.copy()
        renderer.render_game_over(screen, Color.WHITE, progress=1.0)
        second_settled = screen.img.copy()

        assert np.array_equal(first_settled, second_settled)


class TestWinnerText:
    def test_a_draw_does_not_raise_with_no_winner(self):
        renderer, screen = _rendered_empty_board()
        renderer.render_game_over(screen, None, progress=1.0)  # must not raise
