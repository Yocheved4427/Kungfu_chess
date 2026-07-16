"""
Unit tests for engine/snapshot.py (PieceSnapshot, BoardSnapshot, GameSnapshot).

Two concerns:
  - Each ``from_*`` classmethod builds the right value objects from a live
    engine object (board tokens decoded into color/kind, status flags
    mirroring GameEngine.is_in_transit/is_airborne/is_in_cooldown, ...).
  - The whole point of a snapshot: once taken, it is frozen in time. A
    snapshot built at time T must keep reporting time-T values no matter
    what happens to the live GameState/board/collections afterward — see
    TestSnapshotIsUnaffectedByLaterMutation.
"""

from __future__ import annotations

import dataclasses

import pytest

from core.models import Color, PendingJump, PendingMove, Position
from engine.board import TextBoard
from engine.game import GameEngine
from engine.game_state import GameState
from engine.snapshot import BoardSnapshot, GameSnapshot, PieceSnapshot


class TestPieceSnapshotFromPiece:
    def test_decodes_white_piece(self):
        snap = PieceSnapshot.from_piece("wK", Position(0, 4))
        assert snap.color is Color.WHITE
        assert snap.kind == "K"
        assert snap.position == Position(0, 4)

    def test_decodes_black_piece(self):
        snap = PieceSnapshot.from_piece("bP", Position(1, 0))
        assert snap.color is Color.BLACK
        assert snap.kind == "P"

    def test_status_flags_default_to_false(self):
        snap = PieceSnapshot.from_piece("wR", Position(0, 0))
        assert snap.is_in_transit is False
        assert snap.is_airborne is False
        assert snap.is_in_cooldown is False

    def test_status_flags_are_passed_through(self):
        snap = PieceSnapshot.from_piece(
            "wR", Position(0, 0), is_in_transit=True, is_airborne=True, is_in_cooldown=True
        )
        assert snap.is_in_transit is True
        assert snap.is_airborne is True
        assert snap.is_in_cooldown is True

    def test_is_frozen(self):
        snap = PieceSnapshot.from_piece("wK", Position(0, 0))
        with pytest.raises(dataclasses.FrozenInstanceError):
            snap.kind = "Q"


class TestBoardSnapshotFromBoard:
    def test_empty_cells_are_none(self):
        board = TextBoard(["wK . ."])
        snap = BoardSnapshot.from_board(board)
        assert snap.get_piece_at(Position(0, 1)) is None
        assert snap.get_piece_at(Position(0, 2)) is None

    def test_occupied_cells_become_piece_snapshots(self):
        board = TextBoard(["wK . bR"])
        snap = BoardSnapshot.from_board(board)

        king = snap.get_piece_at(Position(0, 0))
        assert king.color is Color.WHITE
        assert king.kind == "K"
        assert king.position == Position(0, 0)

        rook = snap.get_piece_at(Position(0, 2))
        assert rook.color is Color.BLACK
        assert rook.kind == "R"

    def test_dimensions_match_the_board(self):
        board = TextBoard(["wK . .", ". . ."])
        snap = BoardSnapshot.from_board(board)
        assert snap.num_rows == board.num_rows
        assert snap.num_cols == board.num_cols

    def test_get_piece_at_out_of_bounds_returns_none(self):
        board = TextBoard(["wK . ."])
        snap = BoardSnapshot.from_board(board)
        assert snap.get_piece_at(Position(-1, 0)) is None
        assert snap.get_piece_at(Position(0, 99)) is None

    def test_without_state_status_flags_default_to_false(self):
        board = TextBoard(["wK . ."])
        snap = BoardSnapshot.from_board(board)
        king = snap.get_piece_at(Position(0, 0))
        assert king.is_in_transit is False
        assert king.is_airborne is False
        assert king.is_in_cooldown is False

    def test_with_state_populates_transit_status(self):
        board = TextBoard(["wK . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        engine.attempt_move(state, Position(0, 0), Position(0, 1))

        snap = BoardSnapshot.from_board(board, state)
        assert snap.get_piece_at(Position(0, 0)).is_in_transit is True

    def test_with_state_populates_airborne_status(self):
        board = TextBoard([". . .", ". wK .", ". . ."])
        engine = GameEngine(board, cell_size=100, jump_duration=1000)
        state = GameState(board=board)
        engine.handle_jump(state, 150, 150)

        snap = BoardSnapshot.from_board(board, state)
        assert snap.get_piece_at(Position(1, 1)).is_airborne is True

    def test_with_state_populates_cooldown_status(self):
        board = TextBoard(["wK . ."])
        engine = GameEngine(board, cell_size=100, move_duration=500, cooldown_duration=1000)
        state = GameState(board=board)
        engine.attempt_move(state, Position(0, 0), Position(0, 1))
        engine.tick(state, 500)  # move arrives, cooldown starts

        snap = BoardSnapshot.from_board(board, state)
        assert snap.get_piece_at(Position(0, 1)).is_in_cooldown is True


class TestGameSnapshotFromState:
    def test_copies_the_plain_fields(self):
        board = TextBoard(["wK . ."])
        state = GameState(board=board, current_time=42, game_over=True, winner=Color.WHITE)
        snap = GameSnapshot.from_state(state)
        assert snap.current_time == 42
        assert snap.game_over is True
        assert snap.winner is Color.WHITE

    def test_pending_and_airborne_become_tuples(self):
        board = TextBoard(["wK . ."])
        state = GameState(board=board)
        state.pending.append(
            PendingMove(piece="wK", from_pos=Position(0, 0), to_pos=Position(0, 1), arrival_time=100)
        )
        state.airborne.append(PendingJump(piece="wK", pos=Position(0, 0), land_time=100))

        snap = GameSnapshot.from_state(state)
        assert snap.pending == (
            PendingMove(piece="wK", from_pos=Position(0, 0), to_pos=Position(0, 1), arrival_time=100),
        )
        assert snap.airborne == (PendingJump(piece="wK", pos=Position(0, 0), land_time=100),)

    def test_is_frozen(self):
        board = TextBoard(["wK . ."])
        snap = GameSnapshot.from_state(GameState(board=board))
        with pytest.raises(dataclasses.FrozenInstanceError):
            snap.current_time = 999


class TestSnapshotIsUnaffectedByLaterMutation:
    """The core guarantee of this module: a GameSnapshot taken at time T
    keeps its time-T values even after the live GameState it was built
    from is mutated in place."""

    def test_board_occupancy_survives_a_later_move(self):
        board = TextBoard(["wR . .", ". . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)

        snap = GameSnapshot.from_state(state)
        assert snap.board.get_piece_at(Position(0, 0)).kind == "R"
        assert snap.board.get_piece_at(Position(1, 0)) is None

        # Mutate the live board out from under the snapshot.
        engine.try_move(state, Position(0, 0), Position(1, 0))
        assert board.get_piece_at(Position(1, 0)) == "wR"  # live board did move

        assert snap.board.get_piece_at(Position(0, 0)).kind == "R"  # snapshot unchanged
        assert snap.board.get_piece_at(Position(1, 0)) is None

    def test_pending_survives_a_later_tick_that_clears_it(self):
        board = TextBoard(["wK . ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        engine.attempt_move(state, Position(0, 0), Position(0, 1))

        snap = GameSnapshot.from_state(state)
        assert len(snap.pending) == 1

        engine.tick(state, 500)  # move arrives; live state.pending empties
        assert state.pending == []

        assert len(snap.pending) == 1  # snapshot still shows the queued move

    def test_current_time_and_game_over_survive_a_later_tick(self):
        board = TextBoard(["wR . .", "bK . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        engine.handle_click(state, 0, 0)    # select wR
        engine.handle_click(state, 0, 100)  # capture bK

        snap = GameSnapshot.from_state(state)
        assert snap.current_time == 0
        assert snap.game_over is False

        engine.tick(state, 1000)  # capture lands, game ends
        assert state.current_time == 1000
        assert state.game_over is True

        assert snap.current_time == 0  # snapshot unchanged
        assert snap.game_over is False

    def test_cooldown_status_survives_a_later_cooldowns_mutation(self):
        board = TextBoard(["wK . ."])
        state = GameState(board=board)

        snap = GameSnapshot.from_state(state)
        assert snap.board.get_piece_at(Position(0, 0)).is_in_cooldown is False

        # Mutate the live state's cooldowns dict directly, after the snapshot.
        state.cooldowns[Position(0, 0)] = state.current_time + 1000

        assert snap.board.get_piece_at(Position(0, 0)).is_in_cooldown is False
