"""
Unit tests for ui/graphics/piece_view.py and the piece-view lifecycle
GraphicsBoardRenderer drives on top of it.

ui/graphics modules (piece_view, graphics_board_renderer, asset_loader,
...) import each other as flat sibling modules (`from img import Img`),
which only resolves if ui/graphics itself is on sys.path — the same
setup main_gui.py does at import time. No other test file needs this,
since nothing else in the suite touches ui/graphics.

Scope:
  - PieceView.sync()'s own diffing (move/jump entry, move's non-looping
    exit via its own next_state_when_finished) — TestPieceViewSync.
  - The two behaviors step 5 of this task asked for: animation state
    survives two consecutive render() calls when nothing changed, and a
    fresh view is created for a piece that just appeared — see
    TestGraphicsBoardRendererPieceViewLifecycle.
"""

from __future__ import annotations

import pathlib
import sys

GRAPHICS_DIR = pathlib.Path(__file__).resolve().parents[2] / "ui" / "graphics"
sys.path.insert(0, str(GRAPHICS_DIR))

from asset_loader import AssetLoader  # noqa: E402
from graphics_board_renderer import GraphicsBoardRenderer  # noqa: E402
from img import Img  # noqa: E402
from piece_state_machine import PieceStateMachine  # noqa: E402
from piece_view import PieceView  # noqa: E402

from core.models import Position  # noqa: E402
from engine.board import TextBoard  # noqa: E402
from engine.game import GameEngine  # noqa: E402
from engine.game_state import GameState  # noqa: E402
from engine.snapshot import GameSnapshot, PieceSnapshot  # noqa: E402
from input.board_mapper import BoardMapper  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PIECES_ROOT = REPO_ROOT / "assets" / "pieces3"
BOARD_PATH = REPO_ROOT / "assets" / "board.png"


def _piece_view(piece_code: str = "wK") -> PieceView:
    states = AssetLoader(PIECES_ROOT).load(piece_code)
    return PieceView(PieceStateMachine(states, start_state="idle"))


def _snapshot(position: Position, **status) -> PieceSnapshot:
    return PieceSnapshot.from_piece("wK", position, **status)


def _renderer() -> GraphicsBoardRenderer:
    board_shape = Img().read(str(BOARD_PATH)).img.shape
    mapper = BoardMapper.from_board_pixels(board_shape[1], board_shape[0], 8, 8)
    return GraphicsBoardRenderer(AssetLoader(PIECES_ROOT), mapper)


class TestPieceViewSync:
    def test_freshly_created_view_starts_idle_when_nothing_is_active(self):
        view = _piece_view()
        view.sync(_snapshot(Position(0, 0)))
        assert view._machine.current_state == "idle"

    def test_freshly_created_view_enters_move_if_already_in_transit(self):
        view = _piece_view()
        view.sync(_snapshot(Position(0, 0), is_in_transit=True))
        assert view._machine.current_state == "move"

    def test_freshly_created_view_enters_jump_if_already_airborne(self):
        view = _piece_view()
        view.sync(_snapshot(Position(0, 0), is_airborne=True))
        assert view._machine.current_state == "jump"

    def test_transit_starting_enters_move(self):
        view = _piece_view()
        view.sync(_snapshot(Position(0, 0)))
        view.sync(_snapshot(Position(0, 0), is_in_transit=True))
        assert view._machine.current_state == "move"

    def test_transit_ending_follows_moves_own_next_state_when_finished(self):
        view = _piece_view()
        view.sync(_snapshot(Position(0, 0), is_in_transit=True))
        assert view._machine.current_state == "move"

        move_next_state = view._machine.states["move"].next_state_when_finished
        view.sync(_snapshot(Position(0, 0)))  # transit ends
        assert view._machine.current_state == move_next_state

    def test_airborne_starting_enters_jump(self):
        view = _piece_view()
        view.sync(_snapshot(Position(0, 0)))
        view.sync(_snapshot(Position(0, 0), is_airborne=True))
        assert view._machine.current_state == "jump"

    def test_staying_in_the_same_status_does_not_retrigger_a_transition(self):
        """Re-sync'ing the *same* status every frame must not re-call
        transition_to() each time — that would reset _entered_at and
        restart the animation from frame 0 on every render."""
        view = _piece_view()
        view.sync(_snapshot(Position(0, 0), is_in_transit=True))
        entered_at_after_first_sync = view._machine._entered_at

        view.sync(_snapshot(Position(0, 0), is_in_transit=True))
        assert view._machine._entered_at == entered_at_after_first_sync
        assert view._machine.current_state == "move"


class TestGraphicsBoardRendererPieceViewLifecycle:
    def test_animation_state_is_preserved_across_two_unchanged_renders(self):
        board = TextBoard(["wK . ."])
        state = GameState(board=board)
        renderer = _renderer()
        screen = Img()

        renderer.render(GameSnapshot.from_state(state), screen)
        view_after_first_render = renderer._piece_views[Position(0, 0)]

        renderer.render(GameSnapshot.from_state(state), screen)
        view_after_second_render = renderer._piece_views[Position(0, 0)]

        # Same PieceView object kept alive, not recreated ...
        assert view_after_second_render is view_after_first_render
        # ... so its PieceStateMachine's timing wasn't reset either.
        assert view_after_second_render._machine.current_state == "idle"

    def test_animation_state_persists_across_frames_while_a_move_is_in_transit(self):
        board = TextBoard(["wR . ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        renderer = _renderer()
        screen = Img()

        renderer.render(GameSnapshot.from_state(state), screen)
        engine.attempt_move(state, Position(0, 0), Position(0, 1))

        renderer.render(GameSnapshot.from_state(state), screen)
        view = renderer._piece_views[Position(0, 0)]
        assert view._machine.current_state == "move"
        entered_at = view._machine._entered_at

        renderer.render(GameSnapshot.from_state(state), screen)
        same_view = renderer._piece_views[Position(0, 0)]
        assert same_view is view
        assert same_view._machine.current_state == "move"
        assert same_view._machine._entered_at == entered_at  # not restarted

    def test_a_fresh_view_is_created_for_a_piece_that_just_appeared(self):
        board = TextBoard(["wK . ."])
        state = GameState(board=board)
        renderer = _renderer()
        screen = Img()

        assert renderer._piece_views == {}  # nothing rendered yet
        renderer.render(GameSnapshot.from_state(state), screen)

        assert Position(0, 0) in renderer._piece_views
        view = renderer._piece_views[Position(0, 0)]
        assert view.snapshot.color.value == "w"
        assert view.snapshot.kind == "K"
        assert view._machine.current_state == "idle"

    def test_a_fresh_view_replaces_the_old_one_once_a_move_arrives(self):
        """First-pass limitation, called out in this task's summary: once
        a queued move arrives, the piece's cell changes atomically (no
        persistent piece identity across cells in this engine), so the
        destination gets a brand-new PieceView rather than inheriting the
        origin's in-progress animation."""
        board = TextBoard(["wR . ."])
        engine = GameEngine(board, cell_size=100, move_duration=500)
        state = GameState(board=board)
        renderer = _renderer()
        screen = Img()

        renderer.render(GameSnapshot.from_state(state), screen)
        engine.attempt_move(state, Position(0, 0), Position(0, 1))
        renderer.render(GameSnapshot.from_state(state), screen)

        engine.tick(state, 500)  # move arrives
        renderer.render(GameSnapshot.from_state(state), screen)

        assert Position(0, 0) not in renderer._piece_views
        new_view = renderer._piece_views[Position(0, 1)]
        assert new_view._machine.current_state == "idle"

    def test_a_fresh_view_is_created_when_a_different_piece_occupies_the_cell(self):
        """A capturing piece overwrites the captured piece's cell rather
        than leaving it briefly empty, so position alone can't identify
        "the same piece" here — color/kind must match too."""
        board = TextBoard(["wR . .", "bK . ."])
        engine = GameEngine(board, cell_size=100, move_duration=1000)
        state = GameState(board=board)
        renderer = _renderer()
        screen = Img()

        renderer.render(GameSnapshot.from_state(state), screen)
        engine.handle_click(state, 0, 0)    # select wR
        engine.handle_click(state, 0, 100)  # capture bK
        engine.tick(state, 1000)            # capture lands

        renderer.render(GameSnapshot.from_state(state), screen)
        view = renderer._piece_views[Position(1, 0)]
        assert view.snapshot.color.value == "w"
        assert view.snapshot.kind == "R"
        assert view._machine.current_state == "idle"
