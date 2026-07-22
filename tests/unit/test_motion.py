"""
Unit tests for ui/graphics/motion.py (interpolate_position).

ui/graphics modules import each other as flat sibling modules, which only
resolves if ui/graphics itself is on sys.path — same setup as
test_piece_view.py/test_graphics_board_renderer_sizing.py (see those
files' own header comments for why). motion.py itself only imports
core.models (a normal package import, not a flat sibling one), so this
sys.path insertion is only needed here for symmetry/consistency with how
every other ui/graphics test file sets itself up, not because
interpolate_position itself needs anything from ui/graphics.

Scope: pure math against hand-built PendingMoves — no board, no engine,
no rendering. GameEngine actually building a real PendingMove's
checkpoints is covered in tests/unit/test_engine.py and
test_realtime_conflicts.py.
"""

from __future__ import annotations

import pathlib
import sys

GRAPHICS_DIR = pathlib.Path(__file__).resolve().parents[2] / "ui" / "graphics"
sys.path.insert(0, str(GRAPHICS_DIR))

from motion import interpolate_position  # noqa: E402

from core.models import MoveCheckpoint, PendingMove, Position  # noqa: E402


def _pm(
    from_pos: Position,
    to_pos: Position,
    start_time: int,
    checkpoints: "tuple[MoveCheckpoint, ...]",
) -> PendingMove:
    return PendingMove(
        piece="wR",
        from_pos=from_pos,
        to_pos=to_pos,
        arrival_time=checkpoints[-1].due_time,
        start_time=start_time,
        checkpoints=checkpoints,
    )


class TestSingleSegmentMove:
    """A 1-cell move: from_pos -> checkpoints[0] (== to_pos), one segment."""

    def setup_method(self):
        self.pm = _pm(
            from_pos=Position(0, 0),
            to_pos=Position(0, 1),
            start_time=0,
            checkpoints=(MoveCheckpoint(Position(0, 1), 200),),
        )

    def test_at_start_time_the_position_is_the_origin(self):
        assert interpolate_position(self.pm, 0) == (0.0, 0.0)

    def test_at_arrival_time_the_position_is_the_destination(self):
        assert interpolate_position(self.pm, 200) == (0.0, 1.0)

    def test_halfway_through_the_position_is_the_midpoint(self):
        row, col = interpolate_position(self.pm, 100)
        assert row == 0.0
        assert col == 0.5

    def test_a_quarter_of_the_way_through(self):
        row, col = interpolate_position(self.pm, 50)
        assert row == 0.0
        assert col == 0.25


class TestMultiSegmentMove:
    """A 3-cell move: from_pos -> cp0 -> cp1 -> cp2(==to_pos), 3 segments."""

    def setup_method(self):
        self.pm = _pm(
            from_pos=Position(0, 0),
            to_pos=Position(0, 3),
            start_time=1000,
            checkpoints=(
                MoveCheckpoint(Position(0, 1), 1200),
                MoveCheckpoint(Position(0, 2), 1400),
                MoveCheckpoint(Position(0, 3), 1600),
            ),
        )

    def test_at_start_time_the_position_is_the_origin(self):
        assert interpolate_position(self.pm, 1000) == (0.0, 0.0)

    def test_at_arrival_time_the_position_is_the_destination(self):
        assert interpolate_position(self.pm, 1600) == (0.0, 3.0)

    def test_exactly_on_an_intermediate_checkpoint(self):
        """At a checkpoint's own due_time, the interpolated position must
        exactly equal that checkpoint's cell -- not slightly before/after
        it, regardless of which of its two bracketing segments the
        lookup picks (t_a <= current_time <= t_b makes both segments'
        boundary conditions agree here)."""
        assert interpolate_position(self.pm, 1200) == (0.0, 1.0)
        assert interpolate_position(self.pm, 1400) == (0.0, 2.0)

    def test_partway_through_the_first_segment(self):
        row, col = interpolate_position(self.pm, 1100)  # halfway from (0,0) to (0,1)
        assert row == 0.0
        assert col == 0.5

    def test_partway_through_the_last_segment(self):
        row, col = interpolate_position(self.pm, 1500)  # halfway from (0,2) to (0,3)
        assert row == 0.0
        assert col == 2.5

    def test_diagonal_move_interpolates_both_axes(self):
        pm = _pm(
            from_pos=Position(0, 0),
            to_pos=Position(2, 2),
            start_time=0,
            checkpoints=(
                MoveCheckpoint(Position(1, 1), 100),
                MoveCheckpoint(Position(2, 2), 200),
            ),
        )
        row, col = interpolate_position(pm, 50)
        assert row == 0.5
        assert col == 0.5


class TestOutOfRangeClamping:
    def setup_method(self):
        self.pm = _pm(
            from_pos=Position(0, 0),
            to_pos=Position(0, 2),
            start_time=1000,
            checkpoints=(
                MoveCheckpoint(Position(0, 1), 1200),
                MoveCheckpoint(Position(0, 2), 1400),
            ),
        )

    def test_before_start_time_clamps_to_the_origin(self):
        assert interpolate_position(self.pm, 0) == (0.0, 0.0)

    def test_after_arrival_time_clamps_to_the_destination(self):
        assert interpolate_position(self.pm, 9999) == (0.0, 2.0)


class TestNoCheckpointData:
    """A PendingMove built directly, without going through
    GameEngine.attempt_move (e.g. in another test) -- checkpoints is
    empty. Only the two endpoints are well-defined in this case."""

    def test_at_or_before_start_time_is_the_origin(self):
        pm = PendingMove(piece="wR", from_pos=Position(0, 0), to_pos=Position(0, 3), arrival_time=300)
        assert interpolate_position(pm, 0) == (0.0, 0.0)

    def test_at_or_after_arrival_time_is_the_destination(self):
        pm = PendingMove(piece="wR", from_pos=Position(0, 0), to_pos=Position(0, 3), arrival_time=300)
        assert interpolate_position(pm, 300) == (0.0, 3.0)
