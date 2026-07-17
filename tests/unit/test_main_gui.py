"""
Unit tests for main_gui.py's --board CLI argument support.

Scope: _load_board() and _parse_args() only — main() itself opens an
OpenCV window and runs an infinite render loop, so it isn't something a
unit test can drive directly. _load_board() reuses the same BoardParser
(input.board_parser) / BoardValidator (engine.board_validator) pair
main.py already uses for its CLI pipeline — no second parser is
introduced, so nothing here re-tests parsing/validation rules already
covered by test_board_parser.py / test_board_validator.py.
"""

from __future__ import annotations

import main_gui

from engine.board import AbstractBoard


class TestParseArgs:
    def test_board_defaults_to_none(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py"])
        args = main_gui._parse_args()
        assert args.board is None

    def test_board_flag_is_parsed(self, monkeypatch, tmp_path):
        board_file = tmp_path / "custom.txt"
        monkeypatch.setattr("sys.argv", ["main_gui.py", "--board", str(board_file)])
        args = main_gui._parse_args()
        assert args.board == board_file


class TestLoadBoard:
    def test_none_falls_back_to_the_standard_layout(self):
        board = main_gui._load_board(None)
        assert board.get_rows() == main_gui.STANDARD_BOARD_ROWS

    def test_valid_custom_board_file_is_loaded(self, tmp_path):
        board_file = tmp_path / "custom_board.txt"
        board_file.write_text("wK . .\n. . .\n. . bK\n")

        board = main_gui._load_board(board_file)

        assert isinstance(board, AbstractBoard)
        assert board.get_rows() == ["wK . .", ". . .", ". . bK"]
        # And it didn't just silently fall back to the standard layout.
        assert board.get_rows() != main_gui.STANDARD_BOARD_ROWS

    def test_missing_file_falls_back_to_the_standard_layout(self, tmp_path, caplog):
        missing_file = tmp_path / "does_not_exist.txt"

        with caplog.at_level("WARNING", logger="main_gui"):
            board = main_gui._load_board(missing_file)

        assert board.get_rows() == main_gui.STANDARD_BOARD_ROWS
        assert "does_not_exist.txt" in caplog.text

    def test_malformed_board_falls_back_to_the_standard_layout(self, tmp_path, caplog):
        """Unknown token ("XX") — same failure BoardValidator already
        raises BoardValidationError("UNKNOWN_TOKEN") for."""
        board_file = tmp_path / "malformed_board.txt"
        board_file.write_text("wK . XX\n. . .\n")

        with caplog.at_level("WARNING", logger="main_gui"):
            board = main_gui._load_board(board_file)

        assert board.get_rows() == main_gui.STANDARD_BOARD_ROWS
        assert "UNKNOWN_TOKEN" in caplog.text

    def test_mismatched_row_widths_falls_back_to_the_standard_layout(self, tmp_path, caplog):
        board_file = tmp_path / "mismatched_board.txt"
        board_file.write_text("wK . .\n. .\n")

        with caplog.at_level("WARNING", logger="main_gui"):
            board = main_gui._load_board(board_file)

        assert board.get_rows() == main_gui.STANDARD_BOARD_ROWS
        assert "ROW_WIDTH_MISMATCH" in caplog.text

    def test_empty_file_falls_back_to_the_standard_layout(self, tmp_path, caplog):
        board_file = tmp_path / "empty_board.txt"
        board_file.write_text("")

        with caplog.at_level("WARNING", logger="main_gui"):
            board = main_gui._load_board(board_file)

        assert board.get_rows() == main_gui.STANDARD_BOARD_ROWS
        assert "EMPTY_BOARD" in caplog.text

    def test_does_not_crash_on_a_malformed_file(self, tmp_path):
        """The whole point of the fallback: a bad file must never raise
        out of _load_board()."""
        board_file = tmp_path / "malformed_board.txt"
        board_file.write_text("not a board at all")

        board = main_gui._load_board(board_file)  # must not raise
        assert board.get_rows() == main_gui.STANDARD_BOARD_ROWS
