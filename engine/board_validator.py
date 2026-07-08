from __future__ import annotations

from typing import FrozenSet, List

# ---------------------------------------------------------------------------
# Kung Fu Chess – Board Validator
# ---------------------------------------------------------------------------
# Single responsibility: assert structural and token integrity of board rows.
# ---------------------------------------------------------------------------


class BoardValidationError(ValueError):
    """Raised when a board fails structural or token validation."""


class BoardValidator:
    """Asserts that board rows contain only known tokens and uniform width.

    Injected with ``valid_chars`` so this class stays rule-agnostic; all
    magic values live in ``core.config``.
    """

    def __init__(self, valid_chars: FrozenSet[str]) -> None:
        self._valid_chars = valid_chars

    def validate(self, rows: List[str]) -> None:
        if not rows:
            raise BoardValidationError("EMPTY_BOARD")
        expected_width = len(rows[0].split())
        for row in rows:
            for token in row.split():
                if token not in self._valid_chars:
                    raise BoardValidationError("UNKNOWN_TOKEN")
            if len(row.split()) != expected_width:
                raise BoardValidationError("ROW_WIDTH_MISMATCH")
