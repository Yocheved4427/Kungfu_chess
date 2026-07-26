"""
Unit tests for core/models.py

Scope: Color, Cell, MoveRequest, and same_color in isolation.
Verifies enum values, frozen-dataclass immutability, and equality semantics.
"""

import pytest

from shared.models.color import Color
from shared.models.cell import Cell
from core.models import MoveRequest, same_color


class TestColor:
    def test_white_value(self):
        assert Color.WHITE.value == "w"

    def test_black_value(self):
        assert Color.BLACK.value == "b"

    def test_enum_members(self):
        assert set(Color) == {Color.WHITE, Color.BLACK}


class TestSameColor:
    def test_two_white_pieces_are_same_color(self):
        assert same_color("wK", "wR") is True

    def test_two_black_pieces_are_same_color(self):
        assert same_color("bK", "bQ") is True

    def test_white_and_black_are_not_same_color(self):
        assert same_color("wK", "bK") is False

    def test_none_first_argument_is_false(self):
        assert same_color(None, "wK") is False

    def test_none_second_argument_is_false(self):
        assert same_color("wK", None) is False

    def test_both_none_is_false(self):
        assert same_color(None, None) is False

    def test_empty_cell_token_never_matches_a_real_piece(self):
        """"." starts with a different character than any real piece
        token, so it can never be "the same colour" as one — this is
        what lets friendly-fire checks use same_color(dest, piece)
        directly without a separate "dest != '.'" guard."""
        assert same_color(".", "wK") is False
        assert same_color("wK", ".") is False


class TestCell:
    def test_stores_row_and_col(self):
        pos = Cell(row=3, col=5)
        assert pos.row == 3
        assert pos.col == 5

    def test_equality_by_value(self):
        assert Cell(2, 4) == Cell(2, 4)

    def test_inequality_different_row(self):
        assert Cell(0, 4) != Cell(1, 4)

    def test_inequality_different_col(self):
        assert Cell(2, 0) != Cell(2, 1)

    def test_is_frozen_immutable(self):
        pos = Cell(1, 2)
        with pytest.raises((AttributeError, TypeError)):
            pos.row = 99  # type: ignore[misc]

    def test_hashable_can_be_used_in_set(self):
        positions = {Cell(0, 0), Cell(0, 1), Cell(0, 0)}
        assert len(positions) == 2

    def test_hashable_can_be_used_as_dict_key(self):
        d = {Cell(0, 0): "a", Cell(1, 1): "b"}
        assert d[Cell(0, 0)] == "a"


class TestMoveRequest:
    def test_stores_from_and_to(self):
        src = Cell(6, 4)
        dst = Cell(4, 4)
        move = MoveRequest(from_pos=src, to_pos=dst)
        assert move.from_pos == src
        assert move.to_pos == dst

    def test_equality_by_value(self):
        assert (
            MoveRequest(Cell(1, 0), Cell(3, 0))
            == MoveRequest(Cell(1, 0), Cell(3, 0))
        )

    def test_inequality_different_positions(self):
        assert (
            MoveRequest(Cell(1, 0), Cell(3, 0))
            != MoveRequest(Cell(2, 0), Cell(3, 0))
        )

    def test_is_frozen_immutable(self):
        move = MoveRequest(Cell(0, 0), Cell(1, 1))
        with pytest.raises((AttributeError, TypeError)):
            move.from_pos = Cell(2, 2)  # type: ignore[misc]

    def test_hashable(self):
        moves = {
            MoveRequest(Cell(0, 0), Cell(1, 1)),
            MoveRequest(Cell(0, 0), Cell(1, 1)),
        }
        assert len(moves) == 1
