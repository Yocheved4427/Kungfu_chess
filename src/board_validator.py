from __future__ import annotations

from typing import FrozenSet, List


# ---------------------------------------------------------------------------
# Kung Fu Chess – Board validator
# ---------------------------------------------------------------------------
# Single responsibility: enforce structural and content invariants on a board
# that has already been parsed.  Raises BoardValidationError on the first
# violation so the caller gets a clear, actionable message.
# ---------------------------------------------------------------------------


class BoardValidationError(ValueError):
    """
    Raised when a parsed board fails a structural or content check.
    Inherits from ValueError so callers can catch it broadly if needed.
    """


class BoardValidator:
    """
    Validates a board represented as a list of row strings.

    Rules enforced
    --------------
    1. The board must contain at least one row.
    2. Every row must have the same length (width is inferred from row 0).
    3. Every character must belong to the injected set of valid piece symbols.

    The valid-characters set is injected at construction time so tests can
    supply alternative sets without touching global state.
    """

    def __init__(self, valid_chars: FrozenSet[str]) -> None:
        self._valid_chars = valid_chars

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, rows: List[str]) -> None:
        """
        Validate *rows* against all board rules.

        Parameters
        ----------
        rows:
            The board rows as returned by AbstractBoard.get_rows().

        Raises
        ------
        BoardValidationError
            On the first detected violation.
        """
        self._check_not_empty(rows)
        expected_width = len(rows[0])
        for row_index, row in enumerate(rows):
            self._check_row_width(row, row_index, expected_width)
            self._check_row_chars(row, row_index)

    # ------------------------------------------------------------------
    # Private helpers (each enforces exactly one rule)
    # ------------------------------------------------------------------

    def _check_not_empty(self, rows: List[str]) -> None:
        if not rows:
            raise BoardValidationError("Board contains no rows.")

    def _check_row_width(
        self, row: str, row_index: int, expected_width: int
    ) -> None:
        if len(row) != expected_width:
            raise BoardValidationError(
                f"Row {row_index} has width {len(row)}, "
                f"but expected {expected_width} (inferred from row 0)."
            )

    def _check_row_chars(self, row: str, row_index: int) -> None:
        for col_index, char in enumerate(row):
            if char not in self._valid_chars:
                raise BoardValidationError(
                    f"Invalid character '{char}' "
                    f"at row {row_index}, col {col_index}."
                )
