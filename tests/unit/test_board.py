"""
Unit tests for engine/board.py

Scope: TextBoard in complete isolation — no parser, validator, or I/O.
Every public method and property is exercised, including defensive-copy
guarantees and the empty-board edge case.

Board rows use the current token format (space-separated 2-char tokens):
  "wR wN wB wQ wK wB wN wR"
"""

from engine.board import AbstractBoard, TextBoard
from core.models import Color, Position


_RANK_8 = "wR wN wB wQ wK wB wN wR"   # 8 tokens – standard back rank


class TestTextBoard:
    # --- Construction & encapsulation ---------------------------------------

    def test_get_rows_returns_correct_content(self):
        rows = [_RANK_8, "wP wP wP wP wP wP wP wP"]
        board = TextBoard(rows)
        assert board.get_rows() == rows

    def test_get_rows_returns_copy_not_original(self):
        board = TextBoard([_RANK_8])
        returned = board.get_rows()
        returned[0] = "X X X X X X X X"
        assert board.get_rows()[0] == _RANK_8       # internal state unchanged

    def test_constructor_makes_defensive_copy_of_input(self):
        rows = [_RANK_8]
        board = TextBoard(rows)
        rows[0] = "X X X X X X X X"               # mutate the source list
        assert board.get_rows()[0] == _RANK_8

    def test_implements_abstract_board_interface(self):
        board = TextBoard(["wK ."])
        assert isinstance(board, AbstractBoard)

    # --- num_rows -----------------------------------------------------------

    def test_num_rows_standard_8x8_board(self):
        board = TextBoard([_RANK_8] * 8)
        assert board.num_rows == 8

    def test_num_rows_single_row(self):
        board = TextBoard([". . . ."])
        assert board.num_rows == 1

    def test_num_rows_empty_board(self):
        board = TextBoard([])
        assert board.num_rows == 0

    # --- num_cols -----------------------------------------------------------

    def test_num_cols_standard_8x8_board(self):
        board = TextBoard([_RANK_8] * 8)
        assert board.num_cols == 8

    def test_num_cols_single_token(self):
        board = TextBoard(["wK"])
        assert board.num_cols == 1

    def test_num_cols_empty_board_returns_zero(self):
        board = TextBoard([])
        assert board.num_cols == 0

    # --- render -------------------------------------------------------------

    def test_render_single_row(self):
        board = TextBoard([_RANK_8])
        assert board.render() == _RANK_8

    def test_render_multiple_rows_joined_by_newline(self):
        rows = [_RANK_8, "wP wP wP wP wP wP wP wP", ". . . . . . . ."]
        board = TextBoard(rows)
        assert board.render() == "\n".join(rows)

    def test_render_has_no_trailing_newline(self):
        board = TextBoard([_RANK_8, "bR bN bB bQ bK bB bN bR"])
        assert not board.render().endswith("\n")

    # --- get_piece_at -------------------------------------------------------

    def test_get_piece_at_white_rook_top_left(self):
        board = TextBoard([_RANK_8])
        assert board.get_piece_at(Position(0, 0)) == "wR"

    def test_get_piece_at_white_king(self):
        board = TextBoard([_RANK_8])
        assert board.get_piece_at(Position(0, 4)) == "wK"

    def test_get_piece_at_last_token_in_row(self):
        board = TextBoard([_RANK_8])
        assert board.get_piece_at(Position(0, 7)) == "wR"

    def test_get_piece_at_empty_square(self):
        board = TextBoard([". . . . . . . ."])
        assert board.get_piece_at(Position(0, 3)) == "."

    def test_get_piece_at_row_out_of_bounds_returns_none(self):
        board = TextBoard([_RANK_8])
        assert board.get_piece_at(Position(1, 0)) is None

    def test_get_piece_at_col_out_of_bounds_returns_none(self):
        board = TextBoard([_RANK_8])
        assert board.get_piece_at(Position(0, 8)) is None

    def test_get_piece_at_negative_row_returns_none(self):
        board = TextBoard([_RANK_8])
        assert board.get_piece_at(Position(-1, 0)) is None

    def test_get_piece_at_negative_col_returns_none(self):
        board = TextBoard([_RANK_8])
        assert board.get_piece_at(Position(0, -1)) is None

    # --- get_color_at -------------------------------------------------------

    def test_get_color_at_white_piece(self):
        board = TextBoard([_RANK_8])
        assert board.get_color_at(Position(0, 0)) == Color.WHITE

    def test_get_color_at_black_piece(self):
        board = TextBoard(["bR bN bB bQ bK bB bN bR"])
        assert board.get_color_at(Position(0, 0)) == Color.BLACK

    def test_get_color_at_empty_square_returns_none(self):
        board = TextBoard([". . . . . . . ."])
        assert board.get_color_at(Position(0, 0)) is None

    def test_get_color_at_out_of_bounds_returns_none(self):
        board = TextBoard([_RANK_8])
        assert board.get_color_at(Position(99, 99)) is None

    def test_get_color_at_unknown_prefix_returns_none(self):
        """Token whose first char is neither 'w' nor 'b' yields None."""
        board = TextBoard(["xK"])   # 'x' is not a valid color prefix
        assert board.get_color_at(Position(0, 0)) is None

    # --- move_piece ---------------------------------------------------------

    def test_move_piece_across_rows(self):
        board = TextBoard(["wK .", ". ."])
        board.move_piece(Position(0, 0), Position(1, 1))
        assert board.get_piece_at(Position(0, 0)) == "."
        assert board.get_piece_at(Position(1, 1)) == "wK"

    def test_move_piece_within_same_row(self):
        board = TextBoard(["wK . ."])
        board.move_piece(Position(0, 0), Position(0, 2))
        assert board.get_piece_at(Position(0, 0)) == "."
        assert board.get_piece_at(Position(0, 2)) == "wK"

    def test_move_piece_captures_enemy(self):
        board = TextBoard(["wK bQ"])
        board.move_piece(Position(0, 0), Position(0, 1))
        assert board.get_piece_at(Position(0, 0)) == "."
        assert board.get_piece_at(Position(0, 1)) == "wK"

    def test_move_piece_no_op_when_same_position(self):
        board = TextBoard(["wK ."])
        board.move_piece(Position(0, 0), Position(0, 0))
        assert board.get_piece_at(Position(0, 0)) == "wK"

    def test_move_piece_source_becomes_empty(self):
        board = TextBoard(["wR wN wB wQ wK wB wN wR", ". . . . . . . ."])
        board.move_piece(Position(0, 0), Position(1, 0))
        assert board.get_rows()[0].split()[0] == "."
        assert board.get_rows()[1].split()[0] == "wR"

