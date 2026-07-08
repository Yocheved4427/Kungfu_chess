"""
Integration tests for the full Kung Fu Chess pipeline.

Input format
------------
The io_handler reads a structured text stream with section markers:

    Board:
    wR wN wB wQ wK wB wN wR
    wP wP wP wP wP wP wP wP
    . . . . . . . .
    ...
    bP bP bP bP bP bP bP bP
    bR bN bB bQ bK bB bN bR
    Commands:

Board rows use space-separated 2-char tokens:
  wK wQ wR wB wN wP  (white pieces)
  bK bQ bR bB bN bP  (black pieces)
  .                  (empty square)

Error codes
-----------
  "EMPTY_BOARD"        – no rows between Board: and Commands:
  "ROW_WIDTH_MISMATCH" – rows have different token counts
  "UNKNOWN_TOKEN"      – a token not in VALID_PIECE_CHARS

Scope: ChessIOHandler.run() exercises the complete production pipeline —
BoardParser -> TextBoard -> BoardValidator -> render.
stdin/stdout are simulated with io.StringIO (no monkey-patching).
"""

from __future__ import annotations

import io

import pytest

from src.board_parser import BoardParser
from src.board_validator import BoardValidationError, BoardValidator
from src.config import VALID_PIECE_CHARS
from src.io_handler import ChessIOHandler


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_STANDARD_INPUT = (
    "Board:\n"
    "wR wN wB wQ wK wB wN wR\n"
    "wP wP wP wP wP wP wP wP\n"
    ". . . . . . . .\n"
    ". . . . . . . .\n"
    ". . . . . . . .\n"
    ". . . . . . . .\n"
    "bP bP bP bP bP bP bP bP\n"
    "bR bN bB bQ bK bB bN bR\n"
    "Commands:\n"
)

_STANDARD_BOARD_OUTPUT = (
    "wR wN wB wQ wK wB wN wR\n"
    "wP wP wP wP wP wP wP wP\n"
    ". . . . . . . .\n"
    ". . . . . . . .\n"
    ". . . . . . . .\n"
    ". . . . . . . .\n"
    "bP bP bP bP bP bP bP bP\n"
    "bR bN bB bQ bK bB bN bR\n"
)


def _make_handler(input_text: str) -> tuple[ChessIOHandler, io.StringIO]:
    reader = io.StringIO(input_text)
    writer = io.StringIO()
    handler = ChessIOHandler(
        reader=reader,
        writer=writer,
        parser=BoardParser(),
        validator=BoardValidator(valid_chars=VALID_PIECE_CHARS),
    )
    return handler, writer


# ===========================================================================
# Happy-path: valid input -> correct output
# ===========================================================================

class TestPipelineHappyPath:
    def test_standard_starting_position_round_trips(self):
        handler, writer = _make_handler(_STANDARD_INPUT)
        handler.run()
        assert writer.getvalue() == _STANDARD_BOARD_OUTPUT

    def test_output_ends_with_exactly_one_newline(self):
        handler, writer = _make_handler(_STANDARD_INPUT)
        handler.run()
        output = writer.getvalue()
        assert output.endswith("\n")
        assert not output.endswith("\n\n")

    def test_single_row_board(self):
        handler, writer = _make_handler("Board:\nwR wN wB wQ wK wB wN wR\nCommands:\n")
        handler.run()
        assert writer.getvalue() == "wR wN wB wQ wK wB wN wR\n"

    def test_single_cell_board(self):
        handler, writer = _make_handler("Board:\nwK\nCommands:\n")
        handler.run()
        assert writer.getvalue() == "wK\n"

    def test_all_empty_squares(self):
        handler, writer = _make_handler(
            "Board:\n. . . . . . . .\n. . . . . . . .\nCommands:\n"
        )
        handler.run()
        assert writer.getvalue() == ". . . . . . . .\n. . . . . . . .\n"

    def test_idempotent_canonical_output(self):
        """Running the pipeline twice on the same board produces identical output."""
        handler1, writer1 = _make_handler(_STANDARD_INPUT)
        handler1.run()
        second_input = "Board:\n" + writer1.getvalue() + "Commands:\n"
        handler2, writer2 = _make_handler(second_input)
        handler2.run()
        assert writer1.getvalue() == writer2.getvalue()

    def test_no_commands_section_still_parses_board(self):
        """Commands: is optional; all lines after Board: are treated as board."""
        handler, writer = _make_handler("Board:\nwK .\n. bK\n")
        handler.run()
        assert writer.getvalue() == "wK .\n. bK\n"


# ===========================================================================
# Line-ending normalisation
# ===========================================================================

class TestPipelineLineEndings:
    def test_windows_crlf_board_lines_normalised(self):
        raw = (
            "Board:\r\n"
            "wR wN wB wQ wK wB wN wR\r\n"
            "bR bN bB bQ bK bB bN bR\r\n"
            "Commands:\r\n"
        )
        handler, writer = _make_handler(raw)
        handler.run()
        assert "\r" not in writer.getvalue()
        assert writer.getvalue() == "wR wN wB wQ wK wB wN wR\nbR bN bB bQ bK bB bN bR\n"


# ===========================================================================
# Validation errors propagate through the pipeline
# ===========================================================================

class TestPipelineValidationErrors:
    def test_unknown_token_raises(self):
        handler, _ = _make_handler("Board:\nwR XX wB wQ wK wB wN wR\nCommands:\n")
        with pytest.raises(BoardValidationError, match="UNKNOWN_TOKEN"):
            handler.run()

    def test_row_width_mismatch_raises(self):
        handler, _ = _make_handler(
            "Board:\n"
            ". . . . . . . .\n"
            ". . . . . . .\n"
            "Commands:\n"
        )
        with pytest.raises(BoardValidationError, match="ROW_WIDTH_MISMATCH"):
            handler.run()

    def test_empty_board_section_raises(self):
        handler, _ = _make_handler("Board:\nCommands:\n")
        with pytest.raises(BoardValidationError, match="EMPTY_BOARD"):
            handler.run()

    def test_no_board_section_marker_raises(self):
        """Input without Board: marker yields empty board_lines -> EMPTY_BOARD."""
        handler, _ = _make_handler("wR wN wB wQ wK wB wN wR\n")
        with pytest.raises(BoardValidationError, match="EMPTY_BOARD"):
            handler.run()

    def test_writer_untouched_when_validation_fails(self):
        """No partial output reaches the writer if validation raises."""
        handler, writer = _make_handler("Board:\nwR XX wB wQ wK wB wN wR\nCommands:\n")
        with pytest.raises(BoardValidationError):
            handler.run()
        assert writer.getvalue() == ""


# ===========================================================================
# Dependency Injection: streams are self-contained
# ===========================================================================

class TestPipelineDependencyInjection:
    def test_reader_bytes_consumed_from_injected_stringio(self):
        """The handler must read from our StringIO, not from sys.stdin."""
        reader = io.StringIO("Board:\nwK\nCommands:\n")
        writer = io.StringIO()
        handler = ChessIOHandler(
            reader=reader,
            writer=writer,
            parser=BoardParser(),
            validator=BoardValidator(valid_chars=VALID_PIECE_CHARS),
        )
        handler.run()
        assert reader.tell() > 0

    def test_output_goes_to_injected_writer_not_real_stdout(self, capsys):
        """Nothing should appear on real stdout; all output targets the writer."""
        handler, writer = _make_handler("Board:\nwK\nCommands:\n")
        handler.run()
        captured = capsys.readouterr()
        assert captured.out == ""
        assert writer.getvalue() == "wK\n"

    def test_independent_handler_instances_do_not_share_state(self):
        handler_a, writer_a = _make_handler("Board:\nwK .\nCommands:\n")
        handler_b, writer_b = _make_handler("Board:\nbK .\nCommands:\n")
        handler_a.run()
        handler_b.run()
        assert writer_a.getvalue() == "wK .\n"
        assert writer_b.getvalue() == "bK .\n"
