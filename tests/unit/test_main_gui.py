"""
Unit tests for main_gui.py's CLI argument support (--board, --scale,
--cell-size).

Scope: _load_board(), _parse_args(), and _resolve_cell_size() only —
main() itself opens an OpenCV window and runs an infinite render loop,
so it isn't something a unit test can drive directly. _load_board()
reuses the same BoardParser (input.board_parser) / BoardValidator
(engine.board_validator) pair main.py already uses for its CLI pipeline
— no second parser is introduced, so nothing here re-tests
parsing/validation rules already covered by test_board_parser.py /
test_board_validator.py. Likewise, _resolve_cell_size()'s output is just
an int fed into BoardMapper's own constructor — the mapper's actual
pixel<->cell arithmetic at an arbitrary size is test_board_mapper.py's
job (see its test_round_trips_correctly_at_a_custom_cell_size).
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

    def test_scale_defaults_to_one(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py"])
        args = main_gui._parse_args()
        assert args.scale == 1.0

    def test_cell_size_defaults_to_none(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py"])
        args = main_gui._parse_args()
        assert args.cell_size is None

    def test_scale_flag_is_parsed_as_float(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py", "--scale", "1.5"])
        args = main_gui._parse_args()
        assert args.scale == 1.5

    def test_cell_size_flag_is_parsed_as_int(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py", "--cell-size", "64"])
        args = main_gui._parse_args()
        assert args.cell_size == 64


class TestResolveCellSize:
    def test_neither_flag_given_uses_the_default_unscaled(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py"])
        args = main_gui._parse_args()
        assert main_gui._resolve_cell_size(args, default_cell_size=102) == 102

    def test_scale_multiplies_the_default(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py", "--scale", "2.0"])
        args = main_gui._parse_args()
        assert main_gui._resolve_cell_size(args, default_cell_size=102) == 204

    def test_scale_below_one_shrinks_the_default(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py", "--scale", "0.5"])
        args = main_gui._parse_args()
        assert main_gui._resolve_cell_size(args, default_cell_size=100) == 50

    def test_cell_size_is_used_directly_ignoring_the_default(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py", "--cell-size", "64"])
        args = main_gui._parse_args()
        assert main_gui._resolve_cell_size(args, default_cell_size=102) == 64

    def test_cell_size_wins_when_both_are_given(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv", ["main_gui.py", "--cell-size", "64", "--scale", "3.0"]
        )
        args = main_gui._parse_args()
        assert main_gui._resolve_cell_size(args, default_cell_size=102) == 64

    def test_a_warning_is_logged_when_both_are_given(self, monkeypatch, caplog):
        monkeypatch.setattr(
            "sys.argv", ["main_gui.py", "--cell-size", "64", "--scale", "3.0"]
        )
        args = main_gui._parse_args()

        with caplog.at_level("WARNING", logger="main_gui"):
            main_gui._resolve_cell_size(args, default_cell_size=102)

        assert "--cell-size" in caplog.text
        assert "--scale" in caplog.text

    def test_no_warning_when_only_cell_size_is_given(self, monkeypatch, caplog):
        monkeypatch.setattr("sys.argv", ["main_gui.py", "--cell-size", "64"])
        args = main_gui._parse_args()

        with caplog.at_level("WARNING", logger="main_gui"):
            main_gui._resolve_cell_size(args, default_cell_size=102)

        assert caplog.text == ""


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
