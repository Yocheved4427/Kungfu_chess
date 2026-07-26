"""
Unit tests for server/algebraic.py

Scope: algebraic_to_cell()/cell_to_algebraic() in isolation —
pure string<->Cell conversion, no engine/server involvement.
"""

from __future__ import annotations

import pytest

from shared.models.cell import Cell
from server.algebraic import AlgebraicNotationError, algebraic_to_cell, cell_to_algebraic


class TestAlgebraicToCell:
    def test_a1_is_the_bottom_left_corner(self):
        """a1 -- White's queenside rook's home square -- is row 7, col 0
        (this engine's row 0 is Black's back rank; see module header)."""
        assert algebraic_to_cell("a1") == Cell(row=7, col=0)

    def test_h8_is_the_top_right_corner(self):
        assert algebraic_to_cell("h8") == Cell(row=0, col=7)

    def test_e2_matches_the_white_pawns_starting_square(self):
        """Cross-checked against STANDARD_BOARD_ROWS: row 6, col 4 is 'wP'."""
        assert algebraic_to_cell("e2") == Cell(row=6, col=4)

    def test_e7_matches_a_black_pawns_starting_square(self):
        assert algebraic_to_cell("e7") == Cell(row=1, col=4)

    def test_e4_is_empty_at_game_start(self):
        assert algebraic_to_cell("e4") == Cell(row=4, col=4)

    def test_uppercase_file_is_accepted(self):
        assert algebraic_to_cell("E2") == algebraic_to_cell("e2")

    @pytest.mark.parametrize("bad", ["", "e", "e22", "i1", "e0", "e9", "22", "ee", 123, None])
    def test_invalid_squares_raise(self, bad):
        with pytest.raises(AlgebraicNotationError):
            algebraic_to_cell(bad)


class TestCellToAlgebraic:
    def test_top_left_is_a8(self):
        assert cell_to_algebraic(Cell(row=0, col=0)) == "a8"

    def test_bottom_right_is_h1(self):
        assert cell_to_algebraic(Cell(row=7, col=7)) == "h1"

    @pytest.mark.parametrize("pos", [Cell(-1, 0), Cell(0, -1), Cell(8, 0), Cell(0, 8)])
    def test_out_of_bounds_raises(self, pos):
        with pytest.raises(AlgebraicNotationError):
            cell_to_algebraic(pos)


class TestRoundTrip:
    @pytest.mark.parametrize("square", ["a1", "a8", "h1", "h8", "e2", "e4", "e7", "d5"])
    def test_algebraic_to_cell_then_back_is_identity(self, square):
        assert cell_to_algebraic(algebraic_to_cell(square)) == square

    @pytest.mark.parametrize(
        "pos", [Cell(r, c) for r in range(8) for c in (0, 3, 7)]
    )
    def test_cell_to_algebraic_then_back_is_identity(self, pos):
        assert algebraic_to_cell(cell_to_algebraic(pos)) == pos
