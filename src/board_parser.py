from __future__ import annotations

from typing import List

from src.board import AbstractBoard, TextBoard


# ---------------------------------------------------------------------------
# Kung Fu Chess – Board parser
# ---------------------------------------------------------------------------
# Single responsibility: convert raw text lines into an AbstractBoard.
# This class knows nothing about I/O streams or validation rules.
# ---------------------------------------------------------------------------


class BoardParser:
    """
    Transforms a list of raw text lines (straight from a reader) into an
    AbstractBoard instance.

    Responsibilities
    ----------------
    * Strip platform-specific line endings (\\r\\n, \\n).
    * Discard any trailing blank lines introduced by a file's final newline.
    * Produce a TextBoard; the returned type is AbstractBoard so callers
      depend only on the interface.
    """

    def parse(self, lines: List[str]) -> AbstractBoard:
        rows: List[str] = [line.rstrip("\r\n") for line in lines]

        # Remove blank lines at the end (artifact of EOF newlines).
        while rows and rows[-1] == "":
            rows.pop()

        return TextBoard(rows)
