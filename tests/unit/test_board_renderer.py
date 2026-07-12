"""
Unit tests for engine/board_renderer.py

Scope: BoardRenderer / TextBoardRenderer in isolation from GameEngine.
Rendering (turning board state into a displayable form) is deliberately
kept out of Board — see engine/board.py's module docstring — and lives
here instead, injected into GameEngine as a Strategy (see test_engine.py's
TestGameEngineObserver for the wiring, and TestGameEngineRendererDI below
for a custom-renderer example).
"""

from __future__ import annotations

from core.models import Position
from engine.board import TextBoard
from engine.board_renderer import BoardRenderer, TextBoardRenderer

_RANK_8 = "wR wN wB wQ wK wB wN wR"


class TestTextBoardRenderer:
    def test_is_a_board_renderer(self):
        assert isinstance(TextBoardRenderer(), BoardRenderer)

    def test_render_single_row(self):
        board = TextBoard([_RANK_8])
        assert TextBoardRenderer().render(board) == _RANK_8

    def test_render_multiple_rows_joined_by_newline(self):
        rows = [_RANK_8, "wP wP wP wP wP wP wP wP", ". . . . . . . ."]
        board = TextBoard(rows)
        assert TextBoardRenderer().render(board) == "\n".join(rows)

    def test_render_has_no_trailing_newline(self):
        board = TextBoard([_RANK_8, "bR bN bB bQ bK bB bN bR"])
        assert not TextBoardRenderer().render(board).endswith("\n")

    def test_render_empty_board_is_empty_string(self):
        board = TextBoard([])
        assert TextBoardRenderer().render(board) == ""

    def test_render_reflects_current_state_not_a_snapshot(self):
        """The renderer holds no state of its own — every call reflects
        whatever the board currently looks like."""
        board = TextBoard(["wP ."])
        renderer = TextBoardRenderer()
        assert renderer.render(board) == "wP ."
        board.set_piece_at(Position(0, 0), "wQ")
        assert renderer.render(board) == "wQ ."
