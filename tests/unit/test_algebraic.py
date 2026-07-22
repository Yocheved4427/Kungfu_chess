"""
Unit tests for server/algebraic.py

Scope: algebraic_to_position()/position_to_algebraic() in isolation —
pure string<->Position conversion, no engine/server involvement.
"""

from __future__ import annotations

import pytest

from core.models import Position
from server.algebraic import AlgebraicNotationError, algebraic_to_position, position_to_algebraic


class TestAlgebraicToPosition:
    def test_a1_is_the_bottom_left_corner(self):
        """a1 -- White's queenside rook's home square -- is row 7, col 0
        (this engine's row 0 is Black's back rank; see module header)."""
        assert algebraic_to_position("a1") == Position(row=7, col=0)

    def test_h8_is_the_top_right_corner(self):
        assert algebraic_to_position("h8") == Position(row=0, col=7)

    def test_e2_matches_the_white_pawns_starting_square(self):
        """Cross-checked against STANDARD_BOARD_ROWS: row 6, col 4 is 'wP'."""
        assert algebraic_to_position("e2") == Position(row=6, col=4)

    def test_e7_matches_a_black_pawns_starting_square(self):
        assert algebraic_to_position("e7") == Position(row=1, col=4)

    def test_e4_is_empty_at_game_start(self):
        assert algebraic_to_position("e4") == Position(row=4, col=4)

    def test_uppercase_file_is_accepted(self):
        assert algebraic_to_position("E2") == algebraic_to_position("e2")

    @pytest.mark.parametrize("bad", ["", "e", "e22", "i1", "e0", "e9", "22", "ee", 123, None])
    def test_invalid_squares_raise(self, bad):
        with pytest.raises(AlgebraicNotationError):
            algebraic_to_position(bad)


class TestPositionToAlgebraic:
    def test_top_left_is_a8(self):
        assert position_to_algebraic(Position(row=0, col=0)) == "a8"

    def test_bottom_right_is_h1(self):
        assert position_to_algebraic(Position(row=7, col=7)) == "h1"

    @pytest.mark.parametrize("pos", [Position(-1, 0), Position(0, -1), Position(8, 0), Position(0, 8)])
    def test_out_of_bounds_raises(self, pos):
        with pytest.raises(AlgebraicNotationError):
            position_to_algebraic(pos)


class TestRoundTrip:
    @pytest.mark.parametrize("square", ["a1", "a8", "h1", "h8", "e2", "e4", "e7", "d5"])
    def test_algebraic_to_position_then_back_is_identity(self, square):
        assert position_to_algebraic(algebraic_to_position(square)) == square

    @pytest.mark.parametrize(
        "pos", [Position(r, c) for r in range(8) for c in (0, 3, 7)]
    )
    def test_position_to_algebraic_then_back_is_identity(self, pos):
        assert algebraic_to_position(position_to_algebraic(pos)) == pos
