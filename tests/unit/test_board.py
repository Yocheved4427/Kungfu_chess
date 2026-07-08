"""
Unit tests for src/board.py

Scope: TextBoard in complete isolation — no parser, validator, or I/O.
Every public method and property is exercised, including defensive-copy
guarantees and the empty-board edge case.
"""

from src.board import AbstractBoard, TextBoard


class TestTextBoard:
    # --- Construction & encapsulation ---------------------------------------

    def test_get_rows_returns_correct_content(self):
        rows = ["rnbqkbnr", "pppppppp"]
        board = TextBoard(rows)
        assert board.get_rows() == rows

    def test_get_rows_returns_copy_not_original(self):
        board = TextBoard(["rnbqkbnr"])
        returned = board.get_rows()
        returned[0] = "XXXXXXXX"              # mutate the returned copy
        assert board.get_rows()[0] == "rnbqkbnr"   # internal state unchanged

    def test_constructor_makes_defensive_copy_of_input(self):
        rows = ["rnbqkbnr"]
        board = TextBoard(rows)
        rows[0] = "XXXXXXXX"                  # mutate the original list
        assert board.get_rows()[0] == "rnbqkbnr"

    def test_implements_abstract_board_interface(self):
        board = TextBoard(["k."])
        assert isinstance(board, AbstractBoard)

    # --- num_rows -----------------------------------------------------------

    def test_num_rows_standard_8x8_board(self):
        board = TextBoard(["........"] * 8)
        assert board.num_rows == 8

    def test_num_rows_single_row(self):
        board = TextBoard(["...."])
        assert board.num_rows == 1

    def test_num_rows_empty_board(self):
        board = TextBoard([])
        assert board.num_rows == 0

    # --- num_cols -----------------------------------------------------------

    def test_num_cols_standard_8x8_board(self):
        board = TextBoard(["........"] * 8)
        assert board.num_cols == 8

    def test_num_cols_single_square(self):
        board = TextBoard(["k"])
        assert board.num_cols == 1

    def test_num_cols_empty_board_returns_zero(self):
        board = TextBoard([])
        assert board.num_cols == 0

    # --- render -------------------------------------------------------------

    def test_render_single_row(self):
        board = TextBoard(["rnbqkbnr"])
        assert board.render() == "rnbqkbnr"

    def test_render_multiple_rows_joined_by_newline(self):
        rows = ["rnbqkbnr", "pppppppp", "........"]
        board = TextBoard(rows)
        assert board.render() == "rnbqkbnr\npppppppp\n........"

    def test_render_has_no_trailing_newline(self):
        board = TextBoard(["RNBQKBNR", "PPPPPPPP"])
        assert not board.render().endswith("\n")
