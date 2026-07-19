"""
Unit tests for main_gui.py's two-player split-screen input handling
(_route_click, _OwnColorClickController) and canvas compositing (_hstack).

Scope: exactly the input-routing logic the two-player design discussion
identified as the actual risk here (see main_gui.py's own module-level
comments on _OwnColorClickController and _run_two_player for the full
reasoning) — not the rendering pipeline itself (already covered by
test_render_game_over.py / test_move_history_panel_rendering.py /
test_graphics_board_renderer_sizing.py) and not _new_game (test_main_gui.py).

  * _route_click: a click must reach exactly one of the two controllers,
    translated into that half's own local coordinate space, and never
    the other one — TestRouteClick uses simple recording fakes so this
    is tested as pure dispatch logic, independent of what a real
    controller/engine would do with the click.
  * _OwnColorClickController: the two real bugs this class exists to
    prevent — an enemy-coloured piece must never become selectable, and
    two instances sharing one GameEngine/GameState must never let one
    player's click be misread as "move the OTHER player's selected
    piece" — TestOwnColorClickController and
    TestTwoIndependentControllersDoNotClobberEachOther use a real
    GameEngine/GameState, since this is specifically about interaction
    with real engine state, not pure dispatch.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np

# ui/graphics modules (img, in particular) import each other as flat
# sibling modules, which only resolves if ui/graphics itself is on
# sys.path -- same setup as test_piece_view.py/test_render_game_over.py
# (see those files' own header comments for why). Importing main_gui
# also inserts this path as a side effect of its own module body, but
# this test file does it explicitly rather than relying on that, same
# as every other test file here that touches ui/graphics directly.
GRAPHICS_DIR = pathlib.Path(__file__).resolve().parents[2] / "ui" / "graphics"
sys.path.insert(0, str(GRAPHICS_DIR))

import main_gui  # noqa: E402
from img import Img  # noqa: E402

from core.models import Color, Position  # noqa: E402
from engine.board import TextBoard  # noqa: E402
from engine.game import GameEngine  # noqa: E402
from engine.game_state import GameState  # noqa: E402
from input.board_mapper import BoardMapper  # noqa: E402


class _RecordingController:
    def __init__(self) -> None:
        self.calls: "list[tuple[int, int]]" = []

    def handle_click(self, state, x, y) -> None:
        self.calls.append((x, y))


class TestRouteClick:
    def test_a_click_strictly_inside_the_left_half_reaches_only_left(self):
        left, right = _RecordingController(), _RecordingController()
        main_gui._route_click(50, 70, left_width=100, left_controller=left, right_controller=right, state=None)

        assert left.calls == [(50, 70)]
        assert right.calls == []

    def test_a_click_in_the_right_half_reaches_only_right_with_translated_x(self):
        left, right = _RecordingController(), _RecordingController()
        main_gui._route_click(150, 70, left_width=100, left_controller=left, right_controller=right, state=None)

        assert left.calls == []
        assert right.calls == [(50, 70)]  # 150 - 100

    def test_the_exact_boundary_pixel_goes_to_the_right_half(self):
        """x == left_width is the first column that is NOT part of the
        left half's own board region (a board of width left_width spans
        columns [0, left_width) locally)."""
        left, right = _RecordingController(), _RecordingController()
        main_gui._route_click(100, 0, left_width=100, left_controller=left, right_controller=right, state=None)

        assert left.calls == []
        assert right.calls == [(0, 0)]

    def test_y_is_never_translated_by_either_half(self):
        left, right = _RecordingController(), _RecordingController()
        main_gui._route_click(10, 234, left_width=100, left_controller=left, right_controller=right, state=None)
        main_gui._route_click(210, 234, left_width=100, left_controller=left, right_controller=right, state=None)

        assert left.calls == [(10, 234)]
        assert right.calls == [(110, 234)]

    def test_several_clicks_never_cross_contaminate_the_two_controllers(self):
        left, right = _RecordingController(), _RecordingController()
        clicks = [(5, 5), (250, 5), (99, 20), (100, 20), (300, 40)]
        for x, y in clicks:
            main_gui._route_click(x, y, left_width=100, left_controller=left, right_controller=right, state=None)

        assert left.calls == [(5, 5), (99, 20)]
        assert right.calls == [(150, 5), (0, 20), (200, 40)]


def _shared_game(mapper: BoardMapper):
    board = TextBoard(main_gui.STANDARD_BOARD_ROWS)
    engine = GameEngine(board, mapper=mapper)
    state = GameState(board=board)
    return engine, state


class TestOwnColorClickController:
    def test_clicking_an_own_colour_piece_selects_it(self):
        mapper = BoardMapper(100)
        engine, state = _shared_game(mapper)
        white = main_gui._OwnColorClickController(engine, mapper, Color.WHITE)

        x, y = mapper.cell_to_pixel(6, 0)  # a white pawn
        white.handle_click(state, x, y)

        assert white.selection == Position(6, 0)

    def test_clicking_an_enemy_piece_does_not_select_it(self):
        mapper = BoardMapper(100)
        engine, state = _shared_game(mapper)
        white = main_gui._OwnColorClickController(engine, mapper, Color.WHITE)

        x, y = mapper.cell_to_pixel(1, 0)  # a black pawn
        white.handle_click(state, x, y)

        assert white.selection is None

    def test_clicking_an_empty_cell_with_no_selection_is_a_no_op(self):
        mapper = BoardMapper(100)
        engine, state = _shared_game(mapper)
        white = main_gui._OwnColorClickController(engine, mapper, Color.WHITE)

        x, y = mapper.cell_to_pixel(4, 4)  # empty in the starting position
        white.handle_click(state, x, y)

        assert white.selection is None

    def test_a_legitimate_move_by_the_selected_pieces_owner_proceeds_normally(self):
        """The wrapper must not block real gameplay -- once a piece is
        legitimately selected, moving it works exactly like a bare
        ClickController would."""
        mapper = BoardMapper(100)
        engine, state = _shared_game(mapper)
        white = main_gui._OwnColorClickController(engine, mapper, Color.WHITE)

        from_x, from_y = mapper.cell_to_pixel(6, 0)
        white.handle_click(state, from_x, from_y)
        assert white.selection == Position(6, 0)

        to_x, to_y = mapper.cell_to_pixel(5, 0)
        white.handle_click(state, to_x, to_y)

        assert white.selection is None  # cleared after a move attempt
        assert len(state.pending) == 1
        assert state.pending[0].from_pos == Position(6, 0)


class TestTwoIndependentControllersDoNotClobberEachOther:
    """The concrete bug _OwnColorClickController/two independent
    instances exist to prevent: without this, both halves' clicks
    sharing one GameEngine.handle_click/selection would let one
    player's click on their OWN piece be misread as the OTHER player's
    already-selected piece attempting to move there."""

    def test_selecting_on_one_half_does_not_affect_the_others_selection(self):
        mapper = BoardMapper(100)
        engine, state = _shared_game(mapper)
        white = main_gui._OwnColorClickController(engine, mapper, Color.WHITE)
        black = main_gui._OwnColorClickController(engine, mapper, Color.BLACK)

        wx, wy = mapper.cell_to_pixel(6, 0)
        white.handle_click(state, wx, wy)

        bx, by = mapper.cell_to_pixel(1, 0)
        black.handle_click(state, bx, by)

        assert white.selection == Position(6, 0)
        assert black.selection == Position(1, 0)

    def test_black_selecting_its_own_piece_does_not_trigger_whites_pending_move(self):
        """Without independent selection state, this exact sequence
        (White selects, then Black clicks their own piece) would be
        misread as "move White's selection to where Black just
        clicked" -- see _OwnColorClickController's own docstring."""
        mapper = BoardMapper(100)
        engine, state = _shared_game(mapper)
        white = main_gui._OwnColorClickController(engine, mapper, Color.WHITE)
        black = main_gui._OwnColorClickController(engine, mapper, Color.BLACK)

        wx, wy = mapper.cell_to_pixel(6, 0)
        white.handle_click(state, wx, wy)  # White selects a pawn

        bx, by = mapper.cell_to_pixel(1, 0)
        black.handle_click(state, bx, by)  # Black selects their own pawn

        assert state.pending == []  # no move was queued for either side
        assert white.selection == Position(6, 0)  # White's selection untouched
        assert black.selection == Position(1, 0)


class TestHstack:
    def test_composes_two_images_side_by_side(self):
        left = Img()
        left.img = np.full((10, 20, 4), 1, dtype=np.uint8)
        right = Img()
        right.img = np.full((10, 30, 4), 2, dtype=np.uint8)

        combined = main_gui._hstack(left, right)

        assert combined.img.shape == (10, 50, 4)
        assert (combined.img[:, :20] == 1).all()
        assert (combined.img[:, 20:] == 2).all()
