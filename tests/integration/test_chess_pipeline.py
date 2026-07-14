"""
Integration tests for the full Kung Fu Chess pipeline.

Input format
------------
    Board:
    wR wN wB wQ wK wB wN wR
    ...
    bR bN bB bQ bK bB bN bR
    Commands:
    click <x> <y>
    wait <ms>
    print board

Output is produced only by ``print board`` commands.

Moves are asynchronous: ``click`` only queues a PendingMove.  The board is
mutated only once a ``wait`` command advances the clock past the move's
arrival_time (Chebyshev distance * MOVE_DURATION, default 1000 ms/cell).

Error codes
-----------
  "EMPTY_BOARD"        – no rows in Board: section
  "ROW_WIDTH_MISMATCH" – rows have different token counts
  "UNKNOWN_TOKEN"      – a token not in VALID_PIECE_CHARS

Scope: ChessIOHandler.run() exercises the complete production pipeline:
  BoardParser -> TextBoard -> BoardValidator -> GameEngine -> render.
stdin/stdout are simulated with io.StringIO (no monkey-patching).
"""

from __future__ import annotations

import io

import pytest

from core.config import MOVE_DURATION, VALID_PIECE_CHARS
from core.models import Position
from engine.board_validator import BoardValidationError, BoardValidator
from engine.game import GameEngine
from input.board_parser import BoardParser
from ui.io_handler import ChessIOHandler


# ---------------------------------------------------------------------------
# Shared constants & helpers
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


def _make_handler(
    input_text: str,
    engine_factory=GameEngine,
) -> tuple[ChessIOHandler, io.StringIO]:
    reader = io.StringIO(input_text)
    writer = io.StringIO()
    handler = ChessIOHandler(
        reader=reader,
        writer=writer,
        parser=BoardParser(),
        validator=BoardValidator(valid_chars=VALID_PIECE_CHARS),
        engine_factory=engine_factory,
    )
    return handler, writer


# ===========================================================================
# print board command
# ===========================================================================

class TestPipelinePrintBoard:
    def test_print_board_outputs_initial_board(self):
        handler, writer = _make_handler(
            _STANDARD_INPUT.replace("Commands:\n", "Commands:\nprint board\n")
        )
        handler.run()
        assert writer.getvalue() == _STANDARD_BOARD_OUTPUT

    def test_print_board_multiple_times_produces_repeated_output(self):
        handler, writer = _make_handler(
            _STANDARD_INPUT.replace("Commands:\n", "Commands:\nprint board\nprint board\n")
        )
        handler.run()
        assert writer.getvalue() == _STANDARD_BOARD_OUTPUT * 2

    def test_no_print_board_produces_no_output(self):
        """Without a print board command the writer stays empty."""
        handler, writer = _make_handler(_STANDARD_INPUT)
        handler.run()
        assert writer.getvalue() == ""

    def test_output_ends_with_exactly_one_newline_per_print(self):
        handler, writer = _make_handler(
            _STANDARD_INPUT.replace("Commands:\n", "Commands:\nprint board\n")
        )
        handler.run()
        output = writer.getvalue()
        assert output.endswith("\n")
        assert not output.endswith("\n\n")


# ===========================================================================
# wait command
# ===========================================================================

class TestPipelineWait:
    def test_wait_advances_engine_clock(self):
        captured = []

        def factory(board):
            engine = GameEngine(board)
            original_tick = engine.tick

            def recording_tick(state, ms):
                captured.append(ms)
                original_tick(state, ms)

            engine.tick = recording_tick
            return engine

        handler, _ = _make_handler(
            _STANDARD_INPUT.replace("Commands:\n", "Commands:\nwait 500\n"),
            engine_factory=factory,
        )
        handler.run()
        assert captured == [500]

    def test_unknown_command_line_is_silently_ignored(self):
        handler, writer = _make_handler(
            _STANDARD_INPUT.replace(
                "Commands:\n", "Commands:\nbad command here\nprint board\n"
            )
        )
        handler.run()
        assert writer.getvalue() == _STANDARD_BOARD_OUTPUT

    def test_blank_command_lines_are_silently_ignored(self):
        handler, writer = _make_handler(
            _STANDARD_INPUT.replace(
                "Commands:\n", "Commands:\n\n\nprint board\n"
            )
        )
        handler.run()
        assert writer.getvalue() == _STANDARD_BOARD_OUTPUT


# ===========================================================================
# click command
# ===========================================================================

class TestPipelineClick:
    def test_click_on_piece_selects_it_no_output(self):
        """click alone produces no output; only print board does."""
        handler, writer = _make_handler(
            _STANDARD_INPUT.replace("Commands:\n", "Commands:\nclick 0 0\n")
        )
        handler.run()
        assert writer.getvalue() == ""

    def test_click_then_print_board_prints_unchanged_board(self):
        """A single click (no second click) leaves the board unchanged."""
        handler, writer = _make_handler(
            _STANDARD_INPUT.replace(
                "Commands:\n", "Commands:\nclick 0 0\nprint board\n"
            )
        )
        handler.run()
        assert writer.getvalue() == _STANDARD_BOARD_OUTPUT

    def test_click_sequence_queues_move_without_mutating_board(self):
        """Two clicks queue the move but don't mutate the board immediately —
        moves resolve asynchronously via a later ``wait``."""
        handler, writer = _make_handler(
            "Board:\nwR .\n. .\nCommands:\nclick 0 0\nclick 0 100\nprint board\n"
        )
        handler.run()
        output_rows = writer.getvalue().splitlines()
        assert output_rows[0].split()[0] == "wR"
        assert output_rows[1].split()[0] == "."

    def test_click_sequence_then_wait_moves_piece_on_board(self):
        """Select wR at (0,0), queue a one-square move down, then wait for it
        to arrive before printing."""
        handler, writer = _make_handler(
            f"Board:\nwR .\n. .\nCommands:\nclick 0 0\nclick 0 100\n"
            f"wait {MOVE_DURATION}\nprint board\n"
        )
        handler.run()
        output_rows = writer.getvalue().splitlines()
        # wR should have left (row=0, col=0)
        assert output_rows[0].split()[0] == "."
        # wR should now be at (row=1, col=0)
        assert output_rows[1].split()[0] == "wR"

    def test_out_of_bounds_click_is_silently_ignored(self):
        handler, writer = _make_handler(
            _STANDARD_INPUT.replace(
                "Commands:\n", "Commands:\nclick 9999 9999\nprint board\n"
            )
        )
        handler.run()
        assert writer.getvalue() == _STANDARD_BOARD_OUTPUT


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
            "Board:\n. . . . . . . .\n. . . . . . .\nCommands:\n"
        )
        with pytest.raises(BoardValidationError, match="ROW_WIDTH_MISMATCH"):
            handler.run()

    def test_empty_board_section_raises(self):
        handler, _ = _make_handler("Board:\nCommands:\n")
        with pytest.raises(BoardValidationError, match="EMPTY_BOARD"):
            handler.run()

    def test_no_board_section_marker_raises(self):
        handler, _ = _make_handler("wR wN wB wQ wK wB wN wR\n")
        with pytest.raises(BoardValidationError, match="EMPTY_BOARD"):
            handler.run()

    def test_writer_untouched_when_validation_fails(self):
        handler, writer = _make_handler("Board:\nwR XX wB wQ wK wB wN wR\nCommands:\n")
        with pytest.raises(BoardValidationError):
            handler.run()
        assert writer.getvalue() == ""


# ===========================================================================
# Line-ending normalisation
# ===========================================================================

class TestPipelineLineEndings:
    def test_windows_crlf_normalised(self):
        raw = (
            "Board:\r\n"
            "wR wN wB wQ wK wB wN wR\r\n"
            "bR bN bB bQ bK bB bN bR\r\n"
            "Commands:\r\n"
            "print board\r\n"
        )
        handler, writer = _make_handler(raw)
        handler.run()
        assert "\r" not in writer.getvalue()
        assert writer.getvalue() == (
            "wR wN wB wQ wK wB wN wR\n"
            "bR bN bB bQ bK bB bN bR\n"
        )


# ===========================================================================
# Dependency Injection
# ===========================================================================

class TestPipelineDependencyInjection:
    def test_reader_consumed_from_injected_stringio(self):
        reader = io.StringIO("Board:\nwK\nCommands:\n")
        writer = io.StringIO()
        handler = ChessIOHandler(
            reader=reader,
            writer=writer,
            parser=BoardParser(),
            validator=BoardValidator(valid_chars=VALID_PIECE_CHARS),
            engine_factory=GameEngine,
        )
        handler.run()
        assert reader.tell() > 0

    def test_output_goes_to_injected_writer_not_real_stdout(self, capsys):
        handler, writer = _make_handler(
            "Board:\nwK\nCommands:\nprint board\n"
        )
        handler.run()
        captured = capsys.readouterr()
        assert captured.out == ""
        assert writer.getvalue() == "wK\n"

    def test_custom_engine_factory_is_called(self):
        factory_calls: list = []

        def spy_factory(board):
            factory_calls.append(board)
            return GameEngine(board)

        handler, _ = _make_handler(_STANDARD_INPUT, engine_factory=spy_factory)
        handler.run()
        assert len(factory_calls) == 1

    def test_independent_handler_instances_do_not_share_state(self):
        handler_a, writer_a = _make_handler("Board:\nwK .\nCommands:\nprint board\n")
        handler_b, writer_b = _make_handler("Board:\nbK .\nCommands:\nprint board\n")
        handler_a.run()
        handler_b.run()
        assert writer_a.getvalue() == "wK .\n"
        assert writer_b.getvalue() == "bK .\n"
