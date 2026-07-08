"""
Unit tests for src/board_validator.py

Board format: each row is a space-separated list of tokens.
  Piece tokens : wK wQ wR wB wN wP  (white) / bK bQ bR bB bN bP  (black)
  Empty square : .
  Example row  : "wR wN wB wQ wK wB wN wR"

Error codes emitted by BoardValidator:
  "EMPTY_BOARD"        – validate() called with an empty list
  "ROW_WIDTH_MISMATCH" – a row has a different token count than row 0
  "UNKNOWN_TOKEN"      – a token is not in VALID_PIECE_CHARS

Scope: BoardValidator and BoardValidationError in isolation.
The validator is constructed with the real VALID_PIECE_CHARS from config,
and also with custom frozensets to verify the Dependency Injection contract.
No parser, board, or I/O handler is involved.
"""

import pytest

from src.board_validator import BoardValidationError, BoardValidator
from src.config import VALID_PIECE_CHARS


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

def _make_validator() -> BoardValidator:
    return BoardValidator(valid_chars=VALID_PIECE_CHARS)


# ===========================================================================
# BoardValidationError
# ===========================================================================

class TestBoardValidationError:
    def test_is_subclass_of_value_error(self):
        assert issubclass(BoardValidationError, ValueError)

    def test_carries_message(self):
        err = BoardValidationError("test message")
        assert str(err) == "test message"


# ===========================================================================
# BoardValidator – valid boards (must not raise)
# ===========================================================================

class TestBoardValidatorValidBoards:
    def setup_method(self):
        self.validator = _make_validator()

    def test_validate_standard_starting_position(self):
        rows = [
            "wR wN wB wQ wK wB wN wR",
            "wP wP wP wP wP wP wP wP",
            ". . . . . . . .",
            ". . . . . . . .",
            ". . . . . . . .",
            ". . . . . . . .",
            "bP bP bP bP bP bP bP bP",
            "bR bN bB bQ bK bB bN bR",
        ]
        self.validator.validate(rows)   # must not raise

    def test_validate_single_row_all_empty(self):
        self.validator.validate([". . . . . . . ."])

    def test_validate_single_cell_king(self):
        self.validator.validate(["wK"])

    def test_validate_row_containing_all_valid_tokens(self):
        row = " ".join(sorted(VALID_PIECE_CHARS))
        self.validator.validate([row])


# ===========================================================================
# BoardValidator – empty board
# ===========================================================================

class TestBoardValidatorEmptyBoard:
    def setup_method(self):
        self.validator = _make_validator()

    def test_empty_list_raises(self):
        with pytest.raises(BoardValidationError, match="EMPTY_BOARD"):
            self.validator.validate([])


# ===========================================================================
# BoardValidator – inconsistent row widths
# ===========================================================================

class TestBoardValidatorRowWidths:
    def setup_method(self):
        self.validator = _make_validator()

    def test_second_row_too_few_tokens_raises(self):
        with pytest.raises(BoardValidationError, match="ROW_WIDTH_MISMATCH"):
            self.validator.validate([". . . . . . . .", ". . . . . . ."])

    def test_second_row_too_many_tokens_raises(self):
        with pytest.raises(BoardValidationError, match="ROW_WIDTH_MISMATCH"):
            self.validator.validate([". . . . . . . .", ". . . . . . . . ."])

    def test_last_row_wrong_width_raises(self):
        rows = [". . . . . . . ."] * 7 + [". . . ."]
        with pytest.raises(BoardValidationError, match="ROW_WIDTH_MISMATCH"):
            self.validator.validate(rows)

    def test_single_token_row_width_mismatch(self):
        with pytest.raises(BoardValidationError, match="ROW_WIDTH_MISMATCH"):
            self.validator.validate([". .", "."])


# ===========================================================================
# BoardValidator – invalid tokens
# ===========================================================================

class TestBoardValidatorInvalidTokens:
    def setup_method(self):
        self.validator = _make_validator()

    def test_unknown_two_char_token_raises(self):
        with pytest.raises(BoardValidationError, match="UNKNOWN_TOKEN"):
            self.validator.validate(["XX . . . . . . ."])

    def test_old_single_char_piece_raises(self):
        # Single-char notation is no longer valid in the new token format.
        with pytest.raises(BoardValidationError, match="UNKNOWN_TOKEN"):
            self.validator.validate(["k . . . . . . ."])

    def test_digit_token_raises(self):
        with pytest.raises(BoardValidationError, match="UNKNOWN_TOKEN"):
            self.validator.validate(["1 . . . . . . ."])

    def test_invalid_token_in_second_row_raises(self):
        with pytest.raises(BoardValidationError, match="UNKNOWN_TOKEN"):
            self.validator.validate([". . . . . . . .", ". . . . ZZ . ."])


# ===========================================================================
# BoardValidator – Dependency Injection of valid_chars
# ===========================================================================

class TestBoardValidatorCustomChars:
    def test_custom_valid_chars_accepts_custom_token(self):
        validator = BoardValidator(valid_chars=frozenset({"XX", "."}))
        validator.validate(["XX . XX .", ". XX . XX"])   # must not raise

    def test_custom_valid_chars_rejects_standard_token(self):
        validator = BoardValidator(valid_chars=frozenset({".", "wK"}))
        with pytest.raises(BoardValidationError, match="UNKNOWN_TOKEN"):
            validator.validate(["bK ."])   # bK not in custom set

