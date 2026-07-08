"""
Unit tests for src/config.py

Scope: verify VALID_PIECE_CHARS contains exactly the right 2-char token
symbols and has the correct type.  No other module is imported.
"""

from src.config import VALID_PIECE_CHARS


class TestConfig:
    def test_valid_piece_chars_is_frozenset(self):
        assert isinstance(VALID_PIECE_CHARS, frozenset)

    def test_empty_square_token_included(self):
        assert "." in VALID_PIECE_CHARS

    def test_all_white_piece_tokens_included(self):
        for token in ("wK", "wQ", "wR", "wB", "wN", "wP"):
            assert token in VALID_PIECE_CHARS, f"White token '{token}' missing"

    def test_all_black_piece_tokens_included(self):
        for token in ("bK", "bQ", "bR", "bB", "bN", "bP"):
            assert token in VALID_PIECE_CHARS, f"Black token '{token}' missing"

    def test_single_char_pieces_not_included(self):
        """Old single-char notation must NOT be in the set."""
        for ch in "KQRBNPkqrbnp":
            assert ch not in VALID_PIECE_CHARS

    def test_unknown_token_not_included(self):
        assert "XX" not in VALID_PIECE_CHARS

    def test_digit_not_included(self):
        assert "1" not in VALID_PIECE_CHARS
