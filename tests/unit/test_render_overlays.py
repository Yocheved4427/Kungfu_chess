"""
Unit tests for GraphicsBoardRenderer's selection/cooldown text overlays.

ui/graphics modules import each other as flat sibling modules, which only
resolves if ui/graphics itself is on sys.path — same setup as
test_piece_view.py (see that file's own header comment for why).

Scope:
  - _draw_overlay_label() in isolation: does it actually draw something
    (any pixel change) for a selected cell, for a cell whose piece is in
    cooldown, and does it draw NOTHING for neither case — TestDrawOverlayLabel.
  - render()'s own selected-position wiring: does it call
    _draw_overlay_label with is_selected=True for exactly the cell that
    matches the *selected* argument, and False for every other occupied
    cell — TestRenderWiresSelectionCorrectly. Verified via a plain
    instance-level monkeypatch (a recording stub swapped in for
    _draw_overlay_label), not a mocking library — consistent with the
    rest of this suite's plain, state-based testing style.
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

from core.models import Position  # noqa: E402
from engine.board import TextBoard  # noqa: E402
from engine.game import GameEngine  # noqa: E402
from engine.game_state import GameState  # noqa: E402
from engine.snapshot import GameSnapshot, PieceSnapshot  # noqa: E402
from input.board_mapper import BoardMapper  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PIECES_ROOT = REPO_ROOT / "assets" / "pieces3"
BOARD_PATH = REPO_ROOT / "assets" / "board.png"


def _renderer() -> GraphicsBoardRenderer:
    board_shape = Img().read(str(BOARD_PATH)).img.shape
    mapper = BoardMapper.from_board_pixels(board_shape[1], board_shape[0], 8, 8)
    return GraphicsBoardRenderer(AssetLoader(PIECES_ROOT), mapper)


def _blank_img(width: int = 60, height: int = 60) -> Img:
    img = Img()
    img.img = np.zeros((height, width, 4), dtype=np.uint8)
    return img


class TestDrawOverlayLabel:
    def test_selected_draws_a_label(self):
        renderer = _renderer()
        img = _blank_img()
        before = img.img.copy()

        renderer._draw_overlay_label(img, None, True, 10, 30)

        assert not np.array_equal(img.img, before)

    def test_piece_in_cooldown_draws_a_label(self):
        renderer = _renderer()
        img = _blank_img()
        before = img.img.copy()
        piece = PieceSnapshot.from_piece(
            "wK", Position(0, 0), is_in_cooldown=True, cooldown_remaining_ms=700
        )

        renderer._draw_overlay_label(img, piece, False, 10, 30)

        assert not np.array_equal(img.img, before)

    def test_not_selected_and_not_in_cooldown_draws_nothing(self):
        renderer = _renderer()
        img = _blank_img()
        before = img.img.copy()
        piece = PieceSnapshot.from_piece("wK", Position(0, 0))  # cooldown_remaining_ms=None

        renderer._draw_overlay_label(img, piece, False, 10, 30)

        assert np.array_equal(img.img, before)

    def test_no_piece_and_not_selected_draws_nothing(self):
        """An empty cell is never selected either, but this confirms
        _draw_overlay_label doesn't require a piece at all when it isn't."""
        renderer = _renderer()
        img = _blank_img()
        before = img.img.copy()

        renderer._draw_overlay_label(img, None, False, 10, 30)

        assert np.array_equal(img.img, before)

    def test_a_piece_that_just_left_cooldown_draws_nothing(self):
        """cooldown_remaining_ms is None the instant a cooldown expires
        (see BoardSnapshot.from_board) -- there's no "zero remaining"
        state to render a "0.0s" label for."""
        renderer = _renderer()
        img = _blank_img()
        before = img.img.copy()
        piece = PieceSnapshot.from_piece(
            "wK", Position(0, 0), is_in_cooldown=False, cooldown_remaining_ms=None
        )

        renderer._draw_overlay_label(img, piece, False, 10, 30)

        assert np.array_equal(img.img, before)


class TestRenderWiresSelectionCorrectly:
    def test_is_selected_is_true_only_for_the_matching_position(self):
        board = TextBoard(["wK . bK"])
        state = GameState(board=board)
        renderer = _renderer()

        calls = []
        renderer._draw_overlay_label = (
            lambda window_img, piece, is_selected, x, y: calls.append(is_selected)
        )

        screen = Img()
        renderer.render(GameSnapshot.from_state(state), screen, selected=Position(0, 0))

        assert len(calls) == 2  # one per occupied cell (wK, bK)
        assert calls.count(True) == 1
        assert calls.count(False) == 1

    def test_no_position_is_selected_when_selected_is_none(self):
        board = TextBoard(["wK . bK"])
        state = GameState(board=board)
        renderer = _renderer()

        calls = []
        renderer._draw_overlay_label = (
            lambda window_img, piece, is_selected, x, y: calls.append(is_selected)
        )

        screen = Img()
        renderer.render(GameSnapshot.from_state(state), screen)  # selected defaults to None

        assert calls == [False, False]

    def test_selecting_the_other_piece_flips_which_position_is_selected(self):
        board = TextBoard(["wK . bK"])
        state = GameState(board=board)
        renderer = _renderer()

        positions_marked_selected = []

        def _record(window_img, piece, is_selected, x, y):
            if is_selected:
                positions_marked_selected.append(piece.position)

        renderer._draw_overlay_label = _record

        screen = Img()
        renderer.render(GameSnapshot.from_state(state), screen, selected=Position(0, 2))

        assert positions_marked_selected == [Position(0, 2)]
