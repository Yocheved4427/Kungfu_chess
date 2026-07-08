from __future__ import annotations

from typing import Callable, List, TextIO

from src.board import AbstractBoard
from src.board_parser import BoardParser
from src.board_validator import BoardValidator
from src.engine import GameEngine


# ---------------------------------------------------------------------------
# Kung Fu Chess – I/O handler (Iteration 2)
# ---------------------------------------------------------------------------
# Single responsibility: translate raw text I/O into engine method calls.
#
# The handler owns three concerns:
#   1. Split the input stream into a board section and a commands section.
#   2. Parse + validate the board, then hand it to the injected engine factory.
#   3. Dispatch each command line to the engine; write output only for
#      ``print board``.
#
# All streams and collaborators are constructor-injected for testability.
# ---------------------------------------------------------------------------


class ChessIOHandler:
    """
    Reads a structured text stream, constructs a ``GameEngine``, and executes
    each command by delegating to the engine.

    Input format::

        Board:
        wR wN wB wQ wK wB wN wR
        ...
        Commands:
        click 350 50
        wait 200
        print board

    The ``engine_factory`` callable receives the parsed ``AbstractBoard`` and
    returns a ready ``GameEngine``.  This keeps board creation and engine
    creation decoupled and makes both trivially replaceable in tests.
    """

    def __init__(
        self,
        reader: TextIO,
        writer: TextIO,
        parser: BoardParser,
        validator: BoardValidator,
        engine_factory: Callable[[AbstractBoard], GameEngine],
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._parser = parser
        self._validator = validator
        self._engine_factory = engine_factory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Execute the full read → validate → command-dispatch pipeline."""
        board_lines, command_lines = self._split_sections(
            self._reader.readlines()
        )
        board = self._parser.parse(board_lines)
        self._validator.validate(board.get_rows())
        engine = self._engine_factory(board)
        self._execute_commands(engine, command_lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_sections(
        raw_lines: List[str],
    ) -> tuple[List[str], List[str]]:
        """
        Partition *raw_lines* into board lines and command lines.

        Lines between ``Board:`` and ``Commands:`` (exclusive) are board
        lines with trailing CR/LF stripped.  Lines after ``Commands:`` are
        command lines, stripped of leading/trailing whitespace.
        """
        board_lines: List[str] = []
        command_lines: List[str] = []
        in_board = False
        in_commands = False

        for line in raw_lines:
            clean = line.strip()
            if clean == "Board:":
                in_board = True
                in_commands = False
                continue
            if clean == "Commands:":
                in_board = False
                in_commands = True
                continue
            if in_board:
                board_lines.append(line.rstrip("\r\n"))
            elif in_commands:
                command_lines.append(clean)

        return board_lines, command_lines

    def _execute_commands(
        self, engine: GameEngine, command_lines: List[str]
    ) -> None:
        """Dispatch each command line to the appropriate engine method."""
        for line in command_lines:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "click" and len(parts) == 3:
                engine.handle_click(int(parts[1]), int(parts[2]))
            elif parts[0] == "wait" and len(parts) == 2:
                engine.wait(int(parts[1]))
            elif parts[0] == "print" and len(parts) == 2 and parts[1] == "board":
                self._writer.write(engine.board.render() + "\n")
