"""
Unit tests for ui/graphics/game_over_animation.py (GameOverAnimation).

ui/graphics modules import each other as flat sibling modules, which only
resolves if ui/graphics itself is on sys.path — same setup as
test_piece_view.py (see that file's own header comment for why).

Uses a fake, monotonically-advanceable clock (monkeypatched onto the real
time.time, which game_over_animation.py calls directly) rather than
time.sleep() — this class's whole contract is "elapsed real time drives
progress", so tests need to control that elapsed time precisely and
instantly, not hope a sleep() duration lines up.
"""

from __future__ import annotations

import pathlib
import sys

GRAPHICS_DIR = pathlib.Path(__file__).resolve().parents[2] / "ui" / "graphics"
sys.path.insert(0, str(GRAPHICS_DIR))

from game_over_animation import FADE_DURATION_SEC, GameOverAnimation  # noqa: E402


class _FakeSnapshot:
    def __init__(self, game_over: bool) -> None:
        self.game_over = game_over


class _FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _patched(monkeypatch) -> _FakeClock:
    clock = _FakeClock()
    monkeypatch.setattr("time.time", clock.time)
    return clock


class TestBeforeGameOver:
    def test_is_inactive_before_any_sync(self):
        anim = GameOverAnimation()
        assert anim.is_active is False
        assert anim.progress() == 0.0

    def test_stays_inactive_while_game_over_is_false(self, monkeypatch):
        clock = _patched(monkeypatch)
        anim = GameOverAnimation()
        anim.sync(_FakeSnapshot(game_over=False))
        clock.advance(10.0)
        anim.sync(_FakeSnapshot(game_over=False))
        assert anim.is_active is False
        assert anim.progress() == 0.0


class TestAnimationProgressesWithElapsedTime:
    def test_becomes_active_the_instant_game_over_is_seen(self, monkeypatch):
        _patched(monkeypatch)
        anim = GameOverAnimation()
        anim.sync(_FakeSnapshot(game_over=True))
        assert anim.is_active is True

    def test_progress_at_t0_differs_from_progress_at_the_end_time(self, monkeypatch):
        """The task's own core requirement: the animation's state right
        when the game ends must differ from its state once the fade
        duration has fully elapsed."""
        clock = _patched(monkeypatch)
        anim = GameOverAnimation()
        anim.sync(_FakeSnapshot(game_over=True))

        progress_at_t0 = anim.progress()

        clock.advance(FADE_DURATION_SEC)
        progress_at_end = anim.progress()

        assert progress_at_t0 != progress_at_end
        assert progress_at_t0 == 0.0
        assert progress_at_end == 1.0

    def test_progress_is_a_fraction_partway_through_the_duration(self, monkeypatch):
        clock = _patched(monkeypatch)
        anim = GameOverAnimation()
        anim.sync(_FakeSnapshot(game_over=True))

        clock.advance(FADE_DURATION_SEC / 2)

        assert anim.progress() == 0.5

    def test_progress_is_clamped_to_1_partway_does_not_overshoot(self, monkeypatch):
        clock = _patched(monkeypatch)
        anim = GameOverAnimation()
        anim.sync(_FakeSnapshot(game_over=True))

        clock.advance(FADE_DURATION_SEC * 10)  # way past the end

        assert anim.progress() == 1.0


class TestSettledStateNeverResetsOrLoops:
    def test_progress_stays_pinned_at_1_indefinitely(self, monkeypatch):
        clock = _patched(monkeypatch)
        anim = GameOverAnimation()
        anim.sync(_FakeSnapshot(game_over=True))
        clock.advance(FADE_DURATION_SEC)
        assert anim.progress() == 1.0

        clock.advance(1000.0)  # a long time later
        assert anim.progress() == 1.0

    def test_further_sync_calls_after_game_over_do_not_reset_the_clock(self, monkeypatch):
        """A no-op on every call after the first True -- must not restart
        the fade from 0 on a later frame."""
        clock = _patched(monkeypatch)
        anim = GameOverAnimation()
        anim.sync(_FakeSnapshot(game_over=True))
        clock.advance(FADE_DURATION_SEC)
        assert anim.progress() == 1.0

        anim.sync(_FakeSnapshot(game_over=True))  # another frame, still game_over
        assert anim.progress() == 1.0  # not reset back to 0

    def test_does_not_loop_back_to_0_no_matter_how_much_time_passes(self, monkeypatch):
        clock = _patched(monkeypatch)
        anim = GameOverAnimation()
        anim.sync(_FakeSnapshot(game_over=True))

        for _ in range(5):
            clock.advance(FADE_DURATION_SEC * 3)
            anim.sync(_FakeSnapshot(game_over=True))
            assert anim.progress() == 1.0
