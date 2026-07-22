"""
Unit tests for input/board_mapper.py

Scope: BoardMapper in isolation from GameEngine. This is the single
component in the codebase that does pixel <-> (row, col) arithmetic —
see engine/board.py's module docstring (Board doesn't do it) and
test_engine.py's TestGameEngineMapperDI (GameEngine delegates to it).
"""

from __future__ import annotations

import pytest

from core.models import Position
from input.board_mapper import BoardMapper


class TestConstruction:
    def test_stores_cell_size(self):
        assert BoardMapper(100).cell_size == 100

    def test_zero_cell_size_raises(self):
        with pytest.raises(ValueError):
            BoardMapper(0)

    def test_negative_cell_size_raises(self):
        with pytest.raises(ValueError):
            BoardMapper(-50)


class TestPixelToCell:
    def setup_method(self):
        self.mapper = BoardMapper(100)

    def test_origin_maps_to_row0_col0(self):
        assert self.mapper.pixel_to_cell(0, 0) == Position(0, 0)

    def test_inside_first_cell_still_maps_to_row0_col0(self):
        assert self.mapper.pixel_to_cell(50, 50) == Position(0, 0)

    def test_exact_cell_boundary_rounds_down_to_next_cell(self):
        assert self.mapper.pixel_to_cell(100, 0) == Position(0, 1)
        assert self.mapper.pixel_to_cell(0, 100) == Position(1, 0)

    def test_x_controls_column_y_controls_row(self):
        assert self.mapper.pixel_to_cell(350, 150) == Position(row=1, col=3)

    def test_different_cell_size(self):
        mapper = BoardMapper(50)
        assert mapper.pixel_to_cell(125, 175) == Position(row=3, col=2)


class TestCellToPixel:
    def setup_method(self):
        self.mapper = BoardMapper(100)

    def test_origin_cell_maps_to_pixel_origin(self):
        assert self.mapper.cell_to_pixel(0, 0) == (0, 0)

    def test_row_and_col_scale_independently(self):
        assert self.mapper.cell_to_pixel(row=1, col=3) == (300, 100)

    def test_different_cell_size(self):
        mapper = BoardMapper(50)
        assert mapper.cell_to_pixel(row=3, col=2) == (100, 150)


class TestRoundTrip:
    def test_cell_to_pixel_then_pixel_to_cell_is_identity(self):
        mapper = BoardMapper(100)
        for row, col in [(0, 0), (2, 5), (7, 7)]:
            x, y = mapper.cell_to_pixel(row, col)
            assert mapper.pixel_to_cell(x, y) == Position(row, col)

    def test_round_trips_correctly_at_a_custom_cell_size(self):
        """Same identity, but at a cell size that doesn't match any
        existing fixture in this file (main.py's --scale/--cell-size can
        produce arbitrary sizes like this one) -- the mapper must stay
        internally consistent at whatever size it's actually built with."""
        mapper = BoardMapper(37)
        for row, col in [(0, 0), (2, 5), (7, 7), (3, 1)]:
            x, y = mapper.cell_to_pixel(row, col)
            assert mapper.pixel_to_cell(x, y) == Position(row, col)


class TestFromBoardPixels:
    def test_derives_square_cell_size_from_matching_dimensions(self):
        mapper = BoardMapper.from_board_pixels(
            board_width_px=800, board_height_px=800, num_cols=8, num_rows=8
        )
        assert mapper.cell_size == 100

    def test_uses_the_smaller_axis_to_keep_cells_square(self):
        """400x800 over an 8x8 grid: 50px/col vs 100px/row — cells must
        stay square, so the smaller of the two wins."""
        mapper = BoardMapper.from_board_pixels(
            board_width_px=400, board_height_px=800, num_cols=8, num_rows=8
        )
        assert mapper.cell_size == 50

    def test_non_square_grid(self):
        mapper = BoardMapper.from_board_pixels(
            board_width_px=300, board_height_px=200, num_cols=3, num_rows=2
        )
        assert mapper.cell_size == 100

    def test_zero_num_cols_raises(self):
        with pytest.raises(ValueError):
            BoardMapper.from_board_pixels(100, 100, num_cols=0, num_rows=8)

    def test_zero_num_rows_raises(self):
        with pytest.raises(ValueError):
            BoardMapper.from_board_pixels(100, 100, num_cols=8, num_rows=0)

    def test_result_is_usable_like_any_other_mapper(self):
        mapper = BoardMapper.from_board_pixels(
            board_width_px=800, board_height_px=800, num_cols=8, num_rows=8
        )
        assert mapper.pixel_to_cell(350, 50) == Position(row=0, col=3)


class TestPixelOffset:
    """x_offset/y_offset: where the board's own (0, 0) cell starts within
    a larger canvas -- added for GraphicsBoardRenderer's show_side_panels
    layout, where the board is no longer drawn starting at the canvas's
    own origin (see that class's and render_player_panel's docstrings)."""

    def test_defaults_to_zero_unchanged_from_before_offsets_existed(self):
        mapper = BoardMapper(100)
        assert mapper.cell_to_pixel(0, 0) == (0, 0)
        assert mapper.pixel_to_cell(0, 0) == Position(0, 0)

    def test_cell_to_pixel_shifts_by_the_offset(self):
        mapper = BoardMapper(100, x_offset=50, y_offset=30)
        assert mapper.cell_to_pixel(0, 0) == (50, 30)
        assert mapper.cell_to_pixel(row=1, col=2) == (250, 130)

    def test_pixel_to_cell_shifts_by_the_offset(self):
        mapper = BoardMapper(100, x_offset=50, y_offset=30)
        assert mapper.pixel_to_cell(50, 30) == Position(0, 0)
        assert mapper.pixel_to_cell(60, 40) == Position(0, 0)  # still inside the cell
        assert mapper.pixel_to_cell(150, 30) == Position(0, 1)

    def test_round_trip_holds_with_an_offset(self):
        mapper = BoardMapper(100, x_offset=50, y_offset=30)
        for row, col in [(0, 0), (2, 5), (7, 7)]:
            x, y = mapper.cell_to_pixel(row, col)
            assert mapper.pixel_to_cell(x, y) == Position(row, col)

    def test_a_click_before_the_offset_maps_out_of_bounds(self):
        """A click landing in the margin/panel region reserved before
        the board starts must map to a cell no real board contains --
        AbstractBoard.contains() rejects a negative row/col."""
        mapper = BoardMapper(100, x_offset=50, y_offset=30)
        pos = mapper.pixel_to_cell(10, 10)
        assert pos.row < 0 or pos.col < 0

    def test_x_offset_and_y_offset_are_independent(self):
        mapper = BoardMapper(100, x_offset=50, y_offset=0)
        assert mapper.cell_to_pixel(0, 0) == (50, 0)
        mapper2 = BoardMapper(100, x_offset=0, y_offset=30)
        assert mapper2.cell_to_pixel(0, 0) == (0, 30)
