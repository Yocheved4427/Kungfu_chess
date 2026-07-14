"""
Unit tests for engine/geometry.py

Scope: pure movement-math helpers shared by engine.rules (MoveValidator)
and engine.rule_engine (RuleEngine) — see that module's docstring for why
a single shared implementation replaced two duplicated ones.
"""

from __future__ import annotations

from core.models import Position
from engine.board import TextBoard
from engine.geometry import (
    is_diagonal,
    is_king_step,
    is_knight_shape,
    is_orthogonal,
    path_clear,
    pawn_direction,
    pawn_start_row,
)


def _b(*rows: str) -> TextBoard:
    return TextBoard(list(rows))


class TestIsOrthogonal:
    def test_horizontal_is_orthogonal(self):
        assert is_orthogonal(Position(0, 0), Position(0, 3)) is True

    def test_vertical_is_orthogonal(self):
        assert is_orthogonal(Position(0, 0), Position(5, 0)) is True

    def test_diagonal_is_not_orthogonal(self):
        assert is_orthogonal(Position(0, 0), Position(3, 3)) is False

    def test_same_position_is_not_orthogonal(self):
        assert is_orthogonal(Position(2, 2), Position(2, 2)) is False

    def test_knight_shape_is_not_orthogonal(self):
        assert is_orthogonal(Position(0, 0), Position(1, 2)) is False


class TestIsDiagonal:
    def test_diagonal_is_diagonal(self):
        assert is_diagonal(Position(0, 0), Position(3, 3)) is True

    def test_reverse_diagonal_is_diagonal(self):
        assert is_diagonal(Position(3, 0), Position(0, 3)) is True

    def test_orthogonal_is_not_diagonal(self):
        assert is_diagonal(Position(0, 0), Position(0, 3)) is False

    def test_uneven_deltas_are_not_diagonal(self):
        assert is_diagonal(Position(0, 0), Position(1, 2)) is False

    def test_same_position_is_not_diagonal(self):
        assert is_diagonal(Position(1, 1), Position(1, 1)) is False


class TestIsKnightShape:
    def test_two_by_one_is_knight_shape(self):
        assert is_knight_shape(Position(2, 2), Position(0, 1)) is True

    def test_one_by_two_is_knight_shape(self):
        assert is_knight_shape(Position(2, 2), Position(1, 4)) is True

    def test_straight_line_is_not_knight_shape(self):
        assert is_knight_shape(Position(0, 0), Position(0, 2)) is False

    def test_diagonal_is_not_knight_shape(self):
        assert is_knight_shape(Position(0, 0), Position(2, 2)) is False


class TestIsKingStep:
    def test_one_step_orthogonal_is_a_king_step(self):
        assert is_king_step(Position(1, 1), Position(1, 2)) is True

    def test_one_step_diagonal_is_a_king_step(self):
        assert is_king_step(Position(1, 1), Position(2, 2)) is True

    def test_two_steps_is_not_a_king_step(self):
        assert is_king_step(Position(0, 0), Position(0, 2)) is False

    def test_knight_shape_is_not_a_king_step(self):
        assert is_king_step(Position(0, 0), Position(1, 2)) is False

    def test_same_position_is_not_a_king_step(self):
        assert is_king_step(Position(1, 1), Position(1, 1)) is False


class TestPawnDirection:
    def test_white_advances_toward_decreasing_row(self):
        assert pawn_direction("wP") == -1

    def test_black_advances_toward_increasing_row(self):
        assert pawn_direction("bP") == 1


class TestPawnStartRow:
    def test_white_start_row_is_one_in_front_of_the_last_row(self):
        assert pawn_start_row("wP", num_rows=8) == 6

    def test_black_start_row_is_row_one(self):
        assert pawn_start_row("bP", num_rows=8) == 1

    def test_scales_with_board_height(self):
        assert pawn_start_row("wP", num_rows=4) == 2
        assert pawn_start_row("bP", num_rows=4) == 1


class TestPathClear:
    def test_adjacent_cells_are_always_clear(self):
        board = _b("wR .")
        assert path_clear(board, Position(0, 0), Position(0, 1)) is True

    def test_clear_horizontal_path(self):
        board = _b("wR . . .")
        assert path_clear(board, Position(0, 0), Position(0, 3)) is True

    def test_blocked_by_first_intermediate_square(self):
        board = _b("wR bP . .")
        assert path_clear(board, Position(0, 0), Position(0, 3)) is False

    def test_blocked_by_last_intermediate_square(self):
        board = _b("wR . bP .")
        assert path_clear(board, Position(0, 0), Position(0, 3)) is False

    def test_occupied_destination_does_not_count_as_blocked(self):
        """path_clear only checks squares STRICTLY between from and to —
        the destination's own content is a separate (friendly-fire)
        concern for the caller."""
        board = _b("wR . bN")
        assert path_clear(board, Position(0, 0), Position(0, 2)) is True

    def test_clear_vertical_path(self):
        board = _b("wR . .", ". . .", ". . .")
        assert path_clear(board, Position(0, 0), Position(2, 0)) is True

    def test_blocked_vertical_path(self):
        board = _b("wR . .", "bN . .", ". . .")
        assert path_clear(board, Position(0, 0), Position(2, 0)) is False

    def test_clear_diagonal_path(self):
        board = _b("wB . . .", ". . . .", ". . . .", ". . . .")
        assert path_clear(board, Position(0, 0), Position(3, 3)) is True

    def test_blocked_diagonal_path(self):
        board = _b("wB . . .", ". bN . .", ". . . .")
        assert path_clear(board, Position(0, 0), Position(2, 2)) is False

    def test_reverse_direction_is_symmetric(self):
        board = _b("wR bN . .")
        assert path_clear(board, Position(0, 3), Position(0, 0)) is False
