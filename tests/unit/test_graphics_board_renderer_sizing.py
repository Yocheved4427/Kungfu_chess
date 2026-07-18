"""
Unit tests for GraphicsBoardRenderer's board_size constructor parameter
(added to support main_gui.py's --scale/--cell-size CLI options).

ui/graphics modules import each other as flat sibling modules, which only
resolves if ui/graphics itself is on sys.path — same setup as
test_piece_view.py (see that file's own header comment for why).

Scope: only whether the background board image ends up at the requested
pixel size (or, when board_size is omitted, its native size — today's
unchanged default behaviour). Not in scope: BoardMapper's own pixel<->cell
arithmetic at a given cell size (test_board_mapper.py), or main_gui.py's
--scale/--cell-size -> cell size resolution logic (test_main_gui.py).
"""

from __future__ import annotations

import pathlib
import sys

GRAPHICS_DIR = pathlib.Path(__file__).resolve().parents[2] / "ui" / "graphics"
sys.path.insert(0, str(GRAPHICS_DIR))

from asset_loader import AssetLoader  # noqa: E402
from graphics_board_renderer import GraphicsBoardRenderer  # noqa: E402
from img import Img  # noqa: E402

from input.board_mapper import BoardMapper  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PIECES_ROOT = REPO_ROOT / "assets" / "pieces3"
BOARD_PATH = REPO_ROOT / "assets" / "board.png"


class TestBoardSize:
    def test_omitted_board_size_keeps_the_native_image_resolution(self):
        native_shape = Img().read(str(BOARD_PATH)).img.shape
        renderer = GraphicsBoardRenderer(AssetLoader(PIECES_ROOT), BoardMapper(100))
        assert renderer._board_template.img.shape[:2] == native_shape[:2]

    def test_given_board_size_resizes_the_background_to_match(self):
        cell_size = 60
        board_size = (cell_size * 8, cell_size * 8)  # (width_px, height_px)
        renderer = GraphicsBoardRenderer(
            AssetLoader(PIECES_ROOT), BoardMapper(cell_size), board_size=board_size
        )
        height, width = renderer._board_template.img.shape[:2]
        assert (width, height) == board_size

    def test_board_size_agrees_with_the_mappers_own_cell_size(self):
        """The actual invariant this feature exists to uphold: the
        rendered background's pixel dimensions must equal
        mapper.cell_size * num_cols/num_rows -- not the image's native
        size, and not some other arbitrary size."""
        cell_size = 45
        num_cols = num_rows = 8
        mapper = BoardMapper(cell_size)
        board_size = (cell_size * num_cols, cell_size * num_rows)

        renderer = GraphicsBoardRenderer(
            AssetLoader(PIECES_ROOT), mapper, board_size=board_size
        )

        height, width = renderer._board_template.img.shape[:2]
        assert width == mapper.cell_size * num_cols
        assert height == mapper.cell_size * num_rows
