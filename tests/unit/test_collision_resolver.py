"""
Unit tests for ``CollisionResolver`` (Kungfu Chess).

Covers the two collision *decisions* extracted out of GameEngine.tick()
(see realtime/collision_resolver.py): where a sliding move should stop
short of a friendly mid-route block, and whether an arriving piece is
intercepted by an airborne enemy. This class never mutates the board or
fires events — only GameEngine.tick() (via ``_resolve_due_move``) does,
which is covered end-to-end in test_realtime_conflicts.py and test_jump.py.
"""

from __future__ import annotations

from core.models import PendingJump, PendingMove, Position
from engine.board import TextBoard
from realtime.collision_resolver import CollisionResolver


def _pm(piece: str, from_pos: Position, to_pos: Position) -> PendingMove:
    return PendingMove(piece=piece, from_pos=from_pos, to_pos=to_pos, arrival_time=0)


class TestStopBeforeFriendlyBlock:
    def setup_method(self):
        self.resolver = CollisionResolver()

    def test_returns_none_when_path_is_fully_clear(self):
        board = TextBoard(["wR . . ."])
        pm = _pm("wR", Position(0, 0), Position(0, 3))
        assert self.resolver.stop_before_friendly_block(pm, board) is None

    def test_returns_none_when_an_enemy_blocks_the_route(self):
        """An enemy mid-route is a different case (the whole move is
        dropped by MoveValidator's ordinary path-clear check) — this
        method only ever returns a stop cell for a FRIENDLY blocker."""
        board = TextBoard(["wR . bN ."])
        pm = _pm("wR", Position(0, 0), Position(0, 3))
        assert self.resolver.stop_before_friendly_block(pm, board) is None

    def test_returns_last_clear_cell_before_a_friendly_blocker(self):
        board = TextBoard(["wR . wN ."])
        pm = _pm("wR", Position(0, 0), Position(0, 3))
        assert self.resolver.stop_before_friendly_block(pm, board) == Position(0, 1)

    def test_returns_origin_when_the_very_first_step_is_blocked(self):
        board = TextBoard(["wR wN . ."])
        pm = _pm("wR", Position(0, 0), Position(0, 3))
        assert self.resolver.stop_before_friendly_block(pm, board) == Position(0, 0)

    def test_returns_none_for_adjacent_cells_with_no_intermediate_square(self):
        board = TextBoard(["wR wN"])
        pm = _pm("wR", Position(0, 0), Position(0, 1))
        assert self.resolver.stop_before_friendly_block(pm, board) is None

    def test_returns_none_for_a_knight_shaped_move(self):
        """Not a straight line at all — never participates in this rule."""
        board = TextBoard([". . .", ". . .", "wN . ."])
        pm = _pm("wN", Position(2, 0), Position(0, 1))
        assert self.resolver.stop_before_friendly_block(pm, board) is None

    def test_returns_last_clear_cell_on_a_diagonal_route(self):
        board = TextBoard(["wB . . .", ". . . .", ". . wN .", ". . . ."])
        pm = _pm("wB", Position(0, 0), Position(3, 3))
        assert self.resolver.stop_before_friendly_block(pm, board) == Position(1, 1)


class TestAirborneDefender:
    def setup_method(self):
        self.resolver = CollisionResolver()

    def test_returns_none_when_nothing_is_airborne_at_the_cell(self):
        assert self.resolver.airborne_defender(Position(1, 0), "bR", []) is None

    def test_returns_none_when_the_airborne_piece_is_friendly(self):
        airborne = [PendingJump(piece="wK", pos=Position(1, 0), land_time=1000)]
        assert self.resolver.airborne_defender(Position(1, 0), "wR", airborne) is None

    def test_returns_the_defender_when_it_is_an_enemy(self):
        airborne = [PendingJump(piece="wK", pos=Position(1, 0), land_time=1000)]
        defender = self.resolver.airborne_defender(Position(1, 0), "bR", airborne)
        assert defender is not None
        assert defender.piece == "wK"

    def test_ignores_airborne_pieces_at_other_cells(self):
        airborne = [PendingJump(piece="wK", pos=Position(2, 2), land_time=1000)]
        assert self.resolver.airborne_defender(Position(1, 0), "bR", airborne) is None
