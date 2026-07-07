from __future__ import annotations

from typing import TextIO

from src.board_parser import BoardParser
from src.board_validator import BoardValidator


# ---------------------------------------------------------------------------
# Kung Fu Chess – I/O handler
# ---------------------------------------------------------------------------
# Single responsibility: orchestrate one read-validate-write cycle.
#
# Both the reader and writer are injected as TextIO objects so this class
# can be tested with StringIO fixtures without monkey-patching sys.stdin /
# sys.stdout.
# ---------------------------------------------------------------------------


class ChessIOHandler:
    """
    Reads raw board text from *reader*, parses and validates it, then writes
    the canonical representation to *writer*.

    All collaborators are injected, making the class fully unit-testable and
    compliant with the Dependency Inversion Principle.
    """

    def __init__(
        self,
        reader: TextIO,
        writer: TextIO,
        parser: BoardParser,
        validator: BoardValidator,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._parser = parser
        self._validator = validator

    def run(self) -> None:
        """
        Execute the full pipeline:
          1. Read all lines from the injected reader.
          2. Parse them into an AbstractBoard.
          3. Validate the board.
          4. Write the canonical form to the injected writer.

        A single trailing newline is appended to conform to POSIX text-file
        conventions without producing a blank trailing line.
        """
        lines = self._reader.readlines()
        board = self._parser.parse(lines)
        self._validator.validate(board.get_rows())
        self._writer.write(board.render() + "\n")
