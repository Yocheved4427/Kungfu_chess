from __future__ import annotations

from typing import List

from engine.board import AbstractBoard, TextBoard

# ---------------------------------------------------------------------------
# Kung Fu Chess – Board Parser
# ---------------------------------------------------------------------------
# Single responsibility: convert raw text lines into an AbstractBoard instance.
# ---------------------------------------------------------------------------


class BoardParser:
    """Converts raw text lines into an ``AbstractBoard`` instance.

    Strips line endings and discards trailing blank lines.
    """

    def parse(self, lines: List[str]) -> AbstractBoard:
        rows: List[str] = [line.rstrip("\r\n") for line in lines]
        while rows and rows[-1] == "":
            rows.pop()
        return TextBoard(rows)
