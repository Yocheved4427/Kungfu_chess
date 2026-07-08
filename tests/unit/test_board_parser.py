"""
Unit tests for src/board_parser.py

Scope: BoardParser.parse() in isolation — a real BoardParser is constructed
but no validator or I/O handler is involved.  The output type is checked
against the AbstractBoard interface so the test is decoupled from TextBoard
internals.

Board rows use the current token format (space-separated 2-char tokens), but
the parser itself is format-agnostic: it only strips line-endings and removes
trailing blank lines.
"""

from src.board import AbstractBoard
from src.board_parser import BoardParser


class TestBoardParser:
    def setup_method(self):
        self.parser = BoardParser()

    # --- Line-ending normalisation ------------------------------------------

    def test_parse_strips_unix_newlines(self):
        board = self.parser.parse(["wR wN wB wQ wK wB wN wR\n", "wP wP wP wP wP wP wP wP\n"])
        assert board.get_rows() == ["wR wN wB wQ wK wB wN wR", "wP wP wP wP wP wP wP wP"]

    def test_parse_strips_windows_newlines(self):
        board = self.parser.parse(["wR wN wB wQ wK wB wN wR\r\n", "bR bN bB bQ bK bB bN bR\r\n"])
        assert board.get_rows() == ["wR wN wB wQ wK wB wN wR", "bR bN bB bQ bK bB bN bR"]

    def test_parse_line_without_newline_suffix(self):
        """Last line from readlines() may have no trailing newline."""
        board = self.parser.parse(["wK ."])
        assert board.get_rows() == ["wK ."]

    # --- Trailing blank-line stripping --------------------------------------

    def test_parse_strips_single_trailing_blank_line(self):
        board = self.parser.parse(["wR wN wB wQ wK wB wN wR\n", "\n"])
        assert board.get_rows() == ["wR wN wB wQ wK wB wN wR"]

    def test_parse_strips_multiple_trailing_blank_lines(self):
        board = self.parser.parse(["wR wN wB wQ wK wB wN wR\n", "\n", "\n", "\n"])
        assert board.get_rows() == ["wR wN wB wQ wK wB wN wR"]

    def test_parse_only_blank_lines_produces_empty_board(self):
        board = self.parser.parse(["\n", "\n"])
        assert board.num_rows == 0

    # --- Happy-path correctness ---------------------------------------------

    def test_parse_standard_8x8_board_row_count(self):
        lines = [
            "wR wN wB wQ wK wB wN wR\n",
            "wP wP wP wP wP wP wP wP\n",
            ". . . . . . . .\n",
            ". . . . . . . .\n",
            ". . . . . . . .\n",
            ". . . . . . . .\n",
            "bP bP bP bP bP bP bP bP\n",
            "bR bN bB bQ bK bB bN bR\n",
        ]
        board = self.parser.parse(lines)
        assert board.num_rows == 8

    def test_parse_row_count_preserved_for_internal_rows(self):
        """Blank lines that appear in the middle must NOT be stripped."""
        board = self.parser.parse(["wK .\n", ". bK\n"])
        assert board.num_rows == 2

    # --- Return type --------------------------------------------------------

    def test_parse_returns_abstract_board_instance(self):
        board = self.parser.parse(["wK .\n"])
        assert isinstance(board, AbstractBoard)

