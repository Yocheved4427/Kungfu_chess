"""
Unit tests for GraphicsBoardRenderer's history-panel rendering
(show_history_panel, render_move_history) and the render_scores anchor
fix that had to go with it.

ui/graphics modules import each other as flat sibling modules, which only
resolves if ui/graphics itself is on sys.path — same setup as
test_piece_view.py (see that file's own header comment for why).

Scope: canvas sizing (panel reserves exactly HISTORY_PANEL_WIDTH_PX to
the board's right, or nothing at all when disabled) and render_scores
staying anchored to the board's own right edge rather than drifting into
the panel. Not in scope: MoveHistoryTracker's own move-detection logic
(test_move_history_tracker.py).
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np

GRAPHICS_DIR = pathlib.Path(__file__).resolve().parents[2] / "ui" / "graphics"
sys.path.insert(0, str(GRAPHICS_DIR))

from asset_loader import AssetLoader  # noqa: E402
from graphics_board_renderer import (  # noqa: E402
    HISTORY_PANEL_WIDTH_PX,
    GraphicsBoardRenderer,
)
from img import Img  # noqa: E402

from core.models import Color, Position  # noqa: E402
from engine.board import TextBoard  # noqa: E402
from engine.game_state import GameState  # noqa: E402
from engine.move_history_tracker import CompletedMove  # noqa: E402
from engine.snapshot import GameSnapshot  # noqa: E402
from input.board_mapper import BoardMapper  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PIECES_ROOT = REPO_ROOT / "assets" / "pieces3"
BOARD_PATH = REPO_ROOT / "assets" / "board.png"


def _renderer(show_history_panel: bool = False) -> GraphicsBoardRenderer:
    board_shape = Img().read(str(BOARD_PATH)).img.shape
    mapper = BoardMapper.from_board_pixels(board_shape[1], board_shape[0], 8, 8)
    return GraphicsBoardRenderer(
        AssetLoader(PIECES_ROOT), mapper, show_history_panel=show_history_panel
    )


class TestPanelCanvasSizing:
    def test_panel_disabled_leaves_the_canvas_at_the_boards_own_width(self):
        renderer = _renderer(show_history_panel=False)
        board = TextBoard(["wK . ."])
        state = GameState(board=board)
        screen = Img()

        renderer.render(GameSnapshot.from_state(state), screen)

        assert screen.img.shape[1] == renderer._board_template.img.shape[1]
        assert screen.img.shape[0] == renderer._board_template.img.shape[0]

    def test_panel_enabled_widens_the_canvas_by_exactly_the_panel_width(self):
        renderer = _renderer(show_history_panel=True)
        board = TextBoard(["wK . ."])
        state = GameState(board=board)
        screen = Img()

        renderer.render(GameSnapshot.from_state(state), screen)

        board_width = renderer._board_template.img.shape[1]
        assert screen.img.shape[1] == board_width + HISTORY_PANEL_WIDTH_PX
        assert screen.img.shape[0] == renderer._board_template.img.shape[0]  # height unchanged

    def test_render_move_history_is_a_no_op_when_panel_disabled(self):
        renderer = _renderer(show_history_panel=False)
        board = TextBoard(["wK . ."])
        state = GameState(board=board)
        screen = Img()
        renderer.render(GameSnapshot.from_state(state), screen)
        before = screen.img.copy()

        moves = [CompletedMove(time=1000, color=Color.WHITE, kind="R", destination=Position(0, 2))]
        renderer.render_move_history(screen, moves)

        assert np.array_equal(screen.img, before)


class TestRenderScoresStaysAnchoredToTheBoard:
    def test_black_score_lands_at_the_same_x_position_with_or_without_the_panel(self):
        """render_scores must not drift into the history panel just
        because the canvas got wider -- it should land at the same x
        offset from the board's own left edge whether or not the panel
        is present.

        Verified against blank canvases (not a full render() output):
        render() draws piece sprites whose exact frame depends on
        wall-clock time since each PieceView was constructed, which
        would make a pixel-diff between two separately-built renderers
        flaky. render_scores itself has no such timing dependency, so
        testing it directly avoids that risk entirely.
        """
        renderer_without_panel = _renderer(show_history_panel=False)
        board_h, board_w = renderer_without_panel._board_template.img.shape[:2]

        canvas_without_panel = Img()
        canvas_without_panel.img = np.zeros((board_h, board_w, 4), dtype=np.uint8)
        renderer_without_panel.render_scores(canvas_without_panel, 3, 5)

        renderer_with_panel = _renderer(show_history_panel=True)
        canvas_with_panel = Img()
        canvas_with_panel.img = np.zeros((board_h, board_w + HISTORY_PANEL_WIDTH_PX, 4), dtype=np.uint8)
        renderer_with_panel.render_scores(canvas_with_panel, 3, 5)

        # Compare only the board-width-sized left portion -- the panel
        # region in the second canvas has nothing to compare against.
        assert np.array_equal(canvas_without_panel.img, canvas_with_panel.img[:, :board_w])
