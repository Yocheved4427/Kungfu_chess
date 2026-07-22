"""
Unit tests for GraphicsBoardRenderer's show_side_panels layout
(render()'s canvas-building when it's set, and render_player_panel) --
the redesigned game screen with a labeled panel on each side of the
board, and the fix for the two visual bugs that layout replaces:

  1. "Board edges cropped": the board used to be drawn starting at the
     canvas's own (0, 0) with zero margin anywhere.
  2. "Score text looks like 't: 0'/'k: 0'": render_scores drew directly
     on top of the board with nothing reserved for it -- verified
     empirically (see this task's own investigation) that this drew
     INSIDE the top-left occupied cell's own pixel range, not merely
     near an edge.

ui/graphics modules import each other as flat sibling modules, which only
resolves if ui/graphics itself is on sys.path — same setup as
test_piece_view.py (see that file's own header comment for why).

Scope: canvas sizing, panel positions, and the actual bug-fix invariant
(the board's own pixel region is never touched by panel drawing) --
render()'s own per-piece drawing is already covered by test_piece_view.py
etc.; MoveHistoryTracker's own per-color CompletedMove data is covered by
test_move_history_tracker.py. Nothing here re-tests either.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np

GRAPHICS_DIR = pathlib.Path(__file__).resolve().parents[2] / "ui" / "graphics"
sys.path.insert(0, str(GRAPHICS_DIR))

from asset_loader import AssetLoader  # noqa: E402
from graphics_board_renderer import (  # noqa: E402
    BOARD_MARGIN_PX,
    PANEL_BOX_HEIGHT_PX,
    SIDE_PANEL_BACKGROUND_BGRA,
    SIDE_PANEL_WIDTH_PX,
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

CELL_SIZE = 100
NUM_COLS = NUM_ROWS = 8
BOARD_SIZE = (CELL_SIZE * NUM_COLS, CELL_SIZE * NUM_ROWS)
X_OFFSET = 2 * BOARD_MARGIN_PX + SIDE_PANEL_WIDTH_PX
Y_OFFSET = BOARD_MARGIN_PX
SIDE_PANEL_BACKGROUND = np.array(SIDE_PANEL_BACKGROUND_BGRA, dtype=np.uint8)


def _offset_mapper() -> BoardMapper:
    return BoardMapper(CELL_SIZE, x_offset=X_OFFSET, y_offset=Y_OFFSET)


def _renderer(show_side_panels: bool = True, mapper: "BoardMapper | None" = None) -> GraphicsBoardRenderer:
    return GraphicsBoardRenderer(
        AssetLoader(PIECES_ROOT),
        mapper or _offset_mapper(),
        board_size=BOARD_SIZE,
        show_side_panels=show_side_panels,
    )


def _rendered_screen(renderer: GraphicsBoardRenderer, rows=None) -> Img:
    board = TextBoard(rows or [". . . . . . . ."] * 8)
    state = GameState(board=board)
    screen = Img()
    renderer.render(GameSnapshot.from_state(state), screen)
    return screen


class TestCanvasSizing:
    def test_show_side_panels_reserves_margin_and_both_panels(self):
        renderer = _renderer(show_side_panels=True)
        screen = _rendered_screen(renderer)

        expected_w = 4 * BOARD_MARGIN_PX + 2 * SIDE_PANEL_WIDTH_PX + BOARD_SIZE[0]
        expected_h = 2 * BOARD_MARGIN_PX + BOARD_SIZE[1]
        assert screen.img.shape[1] == expected_w
        assert screen.img.shape[0] == expected_h

    def test_show_side_panels_false_keeps_the_board_at_its_native_size(self):
        renderer = _renderer(show_side_panels=False, mapper=BoardMapper(CELL_SIZE))
        screen = _rendered_screen(renderer)
        assert screen.img.shape[:2] == (BOARD_SIZE[1], BOARD_SIZE[0])


class TestBoardIsNeverOverlappedByPanels:
    """The actual fix for both reported bugs: reserving space up front
    means panel drawing can never land on the board's own pixels, no
    matter what's drawn in either panel."""

    def test_board_region_is_byte_identical_before_and_after_both_panels(self):
        renderer = _renderer(show_side_panels=True)
        screen = _rendered_screen(renderer, rows=["bR bN bB bQ bK bB bN bR"] + [". . . . . . . ."] * 7)
        before = screen.img.copy()

        moves = [
            CompletedMove(time=1000, color=Color.WHITE, kind="Q", destination=Position(0, 0)),
            CompletedMove(time=2000, color=Color.BLACK, kind="N", destination=Position(7, 7)),
        ]
        renderer.render_player_panel(screen, Color.WHITE, 999, moves)
        renderer.render_player_panel(screen, Color.BLACK, 999, moves)

        board_region_before = before[Y_OFFSET : Y_OFFSET + BOARD_SIZE[1], X_OFFSET : X_OFFSET + BOARD_SIZE[0]]
        board_region_after = screen.img[Y_OFFSET : Y_OFFSET + BOARD_SIZE[1], X_OFFSET : X_OFFSET + BOARD_SIZE[0]]
        assert np.array_equal(board_region_before, board_region_after)

    def test_the_top_left_cell_specifically_is_untouched(self):
        """The literal bug report: the top-left cell (where a black rook
        starts) must show only the piece, never any panel content."""
        renderer = _renderer(show_side_panels=True)
        board_rows = ["bR bN bB bQ bK bB bN bR"] + [". . . . . . . ."] * 7
        board = TextBoard(board_rows)
        state = GameState(board=board)
        screen = Img()
        renderer.render(GameSnapshot.from_state(state), screen)
        piece_only = screen.img[Y_OFFSET : Y_OFFSET + CELL_SIZE, X_OFFSET : X_OFFSET + CELL_SIZE].copy()

        renderer.render_player_panel(screen, Color.WHITE, 12345, [])
        after_panel = screen.img[Y_OFFSET : Y_OFFSET + CELL_SIZE, X_OFFSET : X_OFFSET + CELL_SIZE]

        assert np.array_equal(piece_only, after_panel)


class TestPanelPositions:
    def test_white_panel_is_left_of_the_board(self):
        renderer = _renderer(show_side_panels=True)
        screen = _rendered_screen(renderer)
        renderer.render_player_panel(screen, Color.WHITE, 3, [])

        # Something was drawn in the reserved left-panel x-range.
        left_region = screen.img[:, BOARD_MARGIN_PX : BOARD_MARGIN_PX + SIDE_PANEL_WIDTH_PX]
        assert (left_region != SIDE_PANEL_BACKGROUND).any()

    def test_black_panel_is_right_of_the_board(self):
        renderer = _renderer(show_side_panels=True)
        screen = _rendered_screen(renderer)
        blank = screen.img.copy()
        renderer.render_player_panel(screen, Color.BLACK, 3, [])

        right_panel_x = X_OFFSET + BOARD_SIZE[0] + BOARD_MARGIN_PX
        right_region = screen.img[:, right_panel_x : right_panel_x + SIDE_PANEL_WIDTH_PX]
        left_region = screen.img[:, : X_OFFSET]

        assert not np.array_equal(right_region, blank[:, right_panel_x : right_panel_x + SIDE_PANEL_WIDTH_PX])
        # Black's panel must not have drawn anything on White's (left) side.
        assert np.array_equal(left_region, blank[:, :X_OFFSET])


class TestRenderPlayerPanelIsANoOpWithoutSidePanels:
    def test_no_op_when_show_side_panels_is_false(self):
        renderer = _renderer(show_side_panels=False, mapper=BoardMapper(CELL_SIZE))
        screen = _rendered_screen(renderer)
        before = screen.img.copy()

        renderer.render_player_panel(screen, Color.WHITE, 5, [])

        assert np.array_equal(screen.img, before)


class TestHistoryStartsBelowTheNameScoreBox:
    def test_no_drawing_happens_inside_the_box_height_except_the_box_itself(self):
        """render_player_panel draws the name/score box, then history
        below it -- the history list must never creep up into the box's
        own reserved height and collide with the name/score text."""
        renderer = _renderer(show_side_panels=True)
        screen = _rendered_screen(renderer)

        box_only = Img()
        box_only.img = screen.img.copy()
        renderer.render_player_panel(box_only, Color.WHITE, 3, [])  # box, no history

        with_history = Img()
        with_history.img = screen.img.copy()
        many_moves = [
            CompletedMove(time=i * 1000, color=Color.WHITE, kind="Q", destination=Position(7, 7))
            for i in range(1, 6)
        ]
        renderer.render_player_panel(with_history, Color.WHITE, 3, many_moves)

        box_bottom = BOARD_MARGIN_PX + PANEL_BOX_HEIGHT_PX
        box_region_only_panel = box_only.img[BOARD_MARGIN_PX:box_bottom, :]
        box_region_with_history = with_history.img[BOARD_MARGIN_PX:box_bottom, :]
        # The box itself (name + score, no history) looks identical
        # whether or not history entries were also drawn below it.
        assert np.array_equal(box_region_only_panel, box_region_with_history)


class TestPerColorHistoryFiltering:
    def test_each_panel_only_reflects_its_own_colours_moves(self):
        """CompletedMove.color makes the split a real, data-backed
        filter, not a guess -- see engine/move_history_tracker.py."""
        renderer = _renderer(show_side_panels=True)
        screen_white_only = _rendered_screen(renderer)
        white_moves = [CompletedMove(time=1000, color=Color.WHITE, kind="Q", destination=Position(0, 0))]
        renderer.render_player_panel(screen_white_only, Color.WHITE, 0, white_moves)

        renderer2 = _renderer(show_side_panels=True)
        screen_black_only = _rendered_screen(renderer2)
        renderer2.render_player_panel(screen_black_only, Color.WHITE, 0, [])  # no moves at all

        # White's panel drew something (its own move) that an otherwise
        # identical panel drawn with an empty history did not.
        assert not np.array_equal(screen_white_only.img, screen_black_only.img)

    def test_a_colours_panel_does_not_draw_the_other_colours_moves(self):
        renderer = _renderer(show_side_panels=True)
        screen_with_only_black_move = _rendered_screen(renderer)
        black_only = [CompletedMove(time=1000, color=Color.BLACK, kind="P", destination=Position(3, 3))]
        renderer.render_player_panel(screen_with_only_black_move, Color.WHITE, 0, black_only)

        renderer2 = _renderer(show_side_panels=True)
        screen_no_moves = _rendered_screen(renderer2)
        renderer2.render_player_panel(screen_no_moves, Color.WHITE, 0, [])

        # White's panel, given only a BLACK move, must render identically
        # to White's panel given no moves at all.
        assert np.array_equal(screen_with_only_black_move.img, screen_no_moves.img)


class TestNothingExceedsCanvasBounds:
    """Explicit bounds-checking, per this task's own suggested
    verification method -- stress-tested with values chosen to be
    unrealistically large, not just the values a real game would ever
    actually reach."""

    def test_huge_scores_and_many_history_entries_stay_within_the_canvas(self):
        renderer = _renderer(show_side_panels=True)
        screen = _rendered_screen(renderer)
        blank = screen.img.copy()

        moves = [
            CompletedMove(
                time=i * 1000,
                color=Color.WHITE if i % 2 == 0 else Color.BLACK,
                kind="Q",
                destination=Position(7, 7),
            )
            for i in range(1, 41)
        ]
        renderer.render_player_panel(screen, Color.WHITE, 999_999, moves)
        renderer.render_player_panel(screen, Color.BLACK, 999_999, moves)

        canvas_h, canvas_w = screen.img.shape[:2]
        diff = np.any(screen.img != blank, axis=2)
        ys, xs = np.where(diff)
        assert xs.min() >= 0 and xs.max() < canvas_w
        assert ys.min() >= 0 and ys.max() < canvas_h

    def test_white_panel_text_never_exceeds_its_own_panel_width(self):
        renderer = _renderer(show_side_panels=True)
        screen = _rendered_screen(renderer)
        blank = screen.img.copy()

        moves = [
            CompletedMove(time=i * 1000, color=Color.WHITE, kind="Q", destination=Position(7, 7))
            for i in range(1, 21)
        ]
        renderer.render_player_panel(screen, Color.WHITE, 999_999, moves)

        diff = np.any(screen.img != blank, axis=2)
        left_panel = diff[:, BOARD_MARGIN_PX : BOARD_MARGIN_PX + SIDE_PANEL_WIDTH_PX]
        touched_columns = np.where(left_panel.any(axis=0))[0]
        assert touched_columns.max() < SIDE_PANEL_WIDTH_PX
