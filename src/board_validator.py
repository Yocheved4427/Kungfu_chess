from __future__ import annotations
from typing import FrozenSet, List

class BoardValidationError(ValueError):
    pass

class BoardValidator:
    def __init__(self, valid_chars: FrozenSet[str]) -> None:
        self._valid_chars = valid_chars

    def validate(self, rows: List[str]) -> None:
        self._check_not_empty(rows)
        
        
        expected_width = len(rows[0].split())
        
        for row in rows:
            self._check_row_chars(row)
            self._check_row_width(row, expected_width)

    def _check_not_empty(self, rows: List[str]) -> None:
        if not rows:
            raise BoardValidationError("EMPTY_BOARD")

    def _check_row_width(self, row: str, expected_width: int) -> None:
        if len(row.split()) != expected_width:
            raise BoardValidationError("ROW_WIDTH_MISMATCH")

    def _check_row_chars(self, row: str) -> None:
        for token in row.split():
            if token not in self._valid_chars:
                raise BoardValidationError("UNKNOWN_TOKEN")