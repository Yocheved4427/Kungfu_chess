"""
Unit tests for main_gui.py's CLI argument support (--board, --scale,
--cell-size) and its _new_game() restart helper.

Scope: _load_board(), _parse_args(), _resolve_cell_size(), and
_new_game() only — main() itself opens an OpenCV window and runs an
infinite render loop, so it isn't something a unit test can drive
directly. _load_board() reuses the same BoardParser (input.board_parser)
/ BoardValidator (engine.board_validator) pair main.py already uses for
its CLI pipeline — no second parser is introduced, so nothing here
re-tests parsing/validation rules already covered by
test_board_parser.py / test_board_validator.py. Likewise,
_resolve_cell_size()'s output is just an int fed into BoardMapper's own
constructor — the mapper's actual pixel<->cell arithmetic at an
arbitrary size is test_board_mapper.py's job (see its
test_round_trips_correctly_at_a_custom_cell_size).

_parse_args()/_resolve_cell_size() now live in ui.cli; _load_board()/
_new_game()/STANDARD_BOARD_ROWS now live in ui.game_factory — both were
split out of main_gui.py itself (a pure reorganization, no behavior
change) since they're launch-config/game-construction concerns, not the
GUI entry point's own logic (which is now just window/mouse setup and
the outer restart loop).
"""

from __future__ import annotations

import argparse

from core.models import Color, Position
from engine.board import AbstractBoard, TextBoard
from engine.game import GameEngine
from engine.game_state import GameState
from input.board_mapper import BoardMapper
from ui import cli, game_factory


class TestParseArgs:
    def test_board_defaults_to_none(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py"])
        args = cli._parse_args()
        assert args.board is None

    def test_board_flag_is_parsed(self, monkeypatch, tmp_path):
        board_file = tmp_path / "custom.txt"
        monkeypatch.setattr("sys.argv", ["main_gui.py", "--board", str(board_file)])
        args = cli._parse_args()
        assert args.board == board_file

    def test_two_player_defaults_to_false(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py"])
        args = cli._parse_args()
        assert args.two_player is False

    def test_two_player_flag_is_parsed(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py", "--two-player"])
        args = cli._parse_args()
        assert args.two_player is True

    def test_scale_defaults_to_one(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py"])
        args = cli._parse_args()
        assert args.scale == 1.0

    def test_cell_size_defaults_to_none(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py"])
        args = cli._parse_args()
        assert args.cell_size is None

    def test_scale_flag_is_parsed_as_float(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py", "--scale", "1.5"])
        args = cli._parse_args()
        assert args.scale == 1.5

    def test_cell_size_flag_is_parsed_as_int(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py", "--cell-size", "64"])
        args = cli._parse_args()
        assert args.cell_size == 64


class TestResolveCellSize:
    def test_neither_flag_given_uses_the_default_unscaled(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py"])
        args = cli._parse_args()
        assert cli._resolve_cell_size(args, default_cell_size=102) == 102

    def test_scale_multiplies_the_default(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py", "--scale", "2.0"])
        args = cli._parse_args()
        assert cli._resolve_cell_size(args, default_cell_size=102) == 204

    def test_scale_below_one_shrinks_the_default(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py", "--scale", "0.5"])
        args = cli._parse_args()
        assert cli._resolve_cell_size(args, default_cell_size=100) == 50

    def test_cell_size_is_used_directly_ignoring_the_default(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main_gui.py", "--cell-size", "64"])
        args = cli._parse_args()
        assert cli._resolve_cell_size(args, default_cell_size=102) == 64

    def test_cell_size_wins_when_both_are_given(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv", ["main_gui.py", "--cell-size", "64", "--scale", "3.0"]
        )
        args = cli._parse_args()
        assert cli._resolve_cell_size(args, default_cell_size=102) == 64

    def test_a_warning_is_logged_when_both_are_given(self, monkeypatch, caplog):
        monkeypatch.setattr(
            "sys.argv", ["main_gui.py", "--cell-size", "64", "--scale", "3.0"]
        )
        args = cli._parse_args()

        with caplog.at_level("WARNING", logger="ui.cli"):
            cli._resolve_cell_size(args, default_cell_size=102)

        assert "--cell-size" in caplog.text
        assert "--scale" in caplog.text

    def test_no_warning_when_only_cell_size_is_given(self, monkeypatch, caplog):
        monkeypatch.setattr("sys.argv", ["main_gui.py", "--cell-size", "64"])
        args = cli._parse_args()

        with caplog.at_level("WARNING", logger="ui.cli"):
            cli._resolve_cell_size(args, default_cell_size=102)

        assert caplog.text == ""


class TestLoadBoard:
    def test_none_falls_back_to_the_standard_layout(self):
        board = game_factory._load_board(None)
        assert board.get_rows() == game_factory.STANDARD_BOARD_ROWS

    def test_valid_custom_board_file_is_loaded(self, tmp_path):
        board_file = tmp_path / "custom_board.txt"
        board_file.write_text("wK . .\n. . .\n. . bK\n")

        board = game_factory._load_board(board_file)

        assert isinstance(board, AbstractBoard)
        assert board.get_rows() == ["wK . .", ". . .", ". . bK"]
        # And it didn't just silently fall back to the standard layout.
        assert board.get_rows() != game_factory.STANDARD_BOARD_ROWS

    def test_missing_file_falls_back_to_the_standard_layout(self, tmp_path, caplog):
        missing_file = tmp_path / "does_not_exist.txt"

        with caplog.at_level("WARNING", logger="ui.game_factory"):
            board = game_factory._load_board(missing_file)

        assert board.get_rows() == game_factory.STANDARD_BOARD_ROWS
        assert "does_not_exist.txt" in caplog.text

    def test_malformed_board_falls_back_to_the_standard_layout(self, tmp_path, caplog):
        """Unknown token ("XX") — same failure BoardValidator already
        raises BoardValidationError("UNKNOWN_TOKEN") for."""
        board_file = tmp_path / "malformed_board.txt"
        board_file.write_text("wK . XX\n. . .\n")

        with caplog.at_level("WARNING", logger="ui.game_factory"):
            board = game_factory._load_board(board_file)

        assert board.get_rows() == game_factory.STANDARD_BOARD_ROWS
        assert "UNKNOWN_TOKEN" in caplog.text

    def test_mismatched_row_widths_falls_back_to_the_standard_layout(self, tmp_path, caplog):
        board_file = tmp_path / "mismatched_board.txt"
        board_file.write_text("wK . .\n. .\n")

        with caplog.at_level("WARNING", logger="ui.game_factory"):
            board = game_factory._load_board(board_file)

        assert board.get_rows() == game_factory.STANDARD_BOARD_ROWS
        assert "ROW_WIDTH_MISMATCH" in caplog.text

    def test_empty_file_falls_back_to_the_standard_layout(self, tmp_path, caplog):
        board_file = tmp_path / "empty_board.txt"
        board_file.write_text("")

        with caplog.at_level("WARNING", logger="ui.game_factory"):
            board = game_factory._load_board(board_file)

        assert board.get_rows() == game_factory.STANDARD_BOARD_ROWS
        assert "EMPTY_BOARD" in caplog.text

    def test_does_not_crash_on_a_malformed_file(self, tmp_path):
        """The whole point of the fallback: a bad file must never raise
        out of _load_board()."""
        board_file = tmp_path / "malformed_board.txt"
        board_file.write_text("not a board at all")

        board = game_factory._load_board(board_file)  # must not raise
        assert board.get_rows() == game_factory.STANDARD_BOARD_ROWS


class TestNewGame:
    """_new_game() is what main()'s restart (R key) calls to rebuild a
    game from scratch — see main()'s own comment on why a restart can't
    just build a fresh GameState and keep reusing the existing
    GameEngine."""

    def _args(self, board_path=None) -> argparse.Namespace:
        return argparse.Namespace(board=board_path, scale=1.0, cell_size=None)

    def test_builds_the_standard_board_when_no_board_arg_was_given(self):
        engine, state = game_factory._new_game(self._args(), BoardMapper(100))
        assert isinstance(engine, GameEngine)
        assert isinstance(state, GameState)
        assert state.board.get_rows() == game_factory.STANDARD_BOARD_ROWS

    def test_uses_the_same_board_file_a_custom_launch_used(self, tmp_path):
        board_file = tmp_path / "custom.txt"
        board_file.write_text("wK . .\n. . .\n. . bK\n")

        _, state = game_factory._new_game(self._args(board_file), BoardMapper(100))

        assert state.board.get_rows() == ["wK . .", ". . .", ". . bK"]

    def test_fresh_game_starts_with_a_clean_state(self):
        engine, state = game_factory._new_game(self._args(), BoardMapper(100))
        assert state.current_time == 0
        assert state.pending == []
        assert state.airborne == []
        assert state.cooldowns == {}
        assert state.game_over is False
        assert state.winner is None
        assert engine.selection is None

    def test_two_calls_return_independent_engines_and_states(self):
        engine1, state1 = game_factory._new_game(self._args(), BoardMapper(100))
        engine2, state2 = game_factory._new_game(self._args(), BoardMapper(100))

        assert engine1 is not engine2
        assert state1 is not state2
        assert state1.board is not state2.board

        # Mutating one game's board must not affect the other's.
        state1.board.set_piece_at(Position(0, 0), ".")
        assert state2.board.get_piece_at(Position(0, 0)) != "."

    def test_a_fresh_engine_correctly_detects_the_new_games_own_king_loss(self):
        """The concrete regression this helper exists to prevent: build
        an engine whose GameOverRule gets primed on a board where White
        has NO king (as some narrow test/custom boards do), end that
        game, then confirm _new_game's fresh engine -- unlike the old
        one -- still correctly detects White losing on a genuinely fresh
        board where White DOES have a king.

        Without a fresh GameEngine (i.e. if a restart only rebuilt
        GameState and kept reusing the old engine), the old engine's
        KingCaptureRule would have frozen "White was never armed" from
        the first game, and White losing its king in the new game would
        silently never be detected as game over.
        """
        stale_board = TextBoard(["wR . .", "bK . ."])
        stale_engine = GameEngine(stale_board, cell_size=100)
        stale_state = GameState(board=stale_board)
        stale_engine.try_move(stale_state, Position(0, 0), Position(1, 0))  # captures bK
        assert stale_state.game_over is True
        assert stale_engine._game_over_rule._white_armed is False  # White never had a king

        fresh_engine, fresh_state = game_factory._new_game(self._args(), BoardMapper(100))
        assert fresh_state.game_over is False  # standard board, game just started

        # White's King is genuinely captured in THIS fresh game.
        fresh_state.board.set_piece_at(Position(7, 4), ".")
        result = fresh_engine._game_over_rule.check(fresh_state.board)
        assert result.is_over is True
        assert result.winner is Color.BLACK
