from __future__ import annotations

import argparse
import time

import cv2
import numpy as np

from asset_loader import AssetLoader
from game_over_animation import GameOverAnimation
from graphics_board_renderer import GraphicsBoardRenderer
from img import Img

from controllers.click_controller import ClickController
from shared.models.color import Color
from shared.models.cell import Cell
from shared.models.board import AbstractBoard, TextBoard
from engine.game import GameEngine
from engine.game_state import GameState
from engine.move_history_tracker import MoveHistoryTracker
from engine.score_tracker import ScoreTracker
from engine.snapshot import BoardSnapshot, GameSnapshot
from input.board_mapper import BoardMapper
from network_client import NetworkClient
from ui.game_factory import _new_game

WINDOW_NAME = "Kung Fu Chess"
ESC = 27

# BGRA background for the network-mode "waiting for the game to start"
# placeholder frame, and the HUD text drawn over the real board once a
# snapshot has arrived -- see _run_network_player.
NETWORK_WAITING_BGRA = (30, 30, 30, 255)


class _OwnColorClickController:
    """A ``ClickController`` restricted to selecting/moving pieces of one
    ``Color`` — two-player mode's per-half input handling.

    Two-player mode can't route both halves' clicks through
    ``GameEngine.handle_click``/``engine.selection`` directly:
    ``GameEngine`` always delegates to one internal ``ClickController``,
    so both halves would share a single ``selection``. A click on the
    right half while the left half already has a piece selected would
    then be read as "move the left half's selected piece to wherever the
    right half just clicked" — ``ClickController.handle_click``'s own
    "switch selection" rule only applies to a *same-colour* click,
    otherwise it's a move attempt (see that class's docstring). Two
    independent ``ClickController`` instances, both wrapping the SAME
    ``GameEngine``/``GameState`` (its methods are stateless, taking
    ``state`` explicitly, so this is safe), each with their own
    ``selection``, fixes that — this class adds the other missing piece:
    restricting each instance to one player's own colour.

    Only guard needed: refuse to SELECT a piece that isn't *own_color*.
    Once nothing else can ever become the held selection, every
    subsequent move-attempt click (which always acts on the CURRENT
    selection) naturally only ever moves an *own_color* piece too — no
    separate check is needed for that case.
    """

    def __init__(self, engine: GameEngine, mapper: BoardMapper, own_color: Color) -> None:
        self._controller = ClickController(engine, mapper)
        self._mapper = mapper
        self._own_color = own_color

    @property
    def selection(self) -> "Cell | None":
        return self._controller.selection

    def handle_click(self, state: GameState, x: int, y: int) -> None:
        if self._controller.selection is None:
            pos = self._mapper.pixel_to_cell(x, y)
            if state.board.contains(pos):
                piece = state.board.get_piece_at(pos)
                if piece is not None and piece != "." and piece[0] != self._own_color.value:
                    return  # not this player's piece -- ignore, don't even try to select
        self._controller.handle_click(state, x, y)


def _route_click(
    x: int,
    y: int,
    left_width: int,
    left_controller: _OwnColorClickController,
    right_controller: _OwnColorClickController,
    state: GameState,
) -> None:
    """Route a raw click at window pixel (*x*, *y*) to whichever half
    owns that region, translating *x* into that half's own local
    coordinate space first — each half's ``BoardMapper`` assumes its own
    board starts at local x=0, so the right half needs *left_width*
    subtracted before its own pixel<->cell math is correct.

    A click at ``x < left_width`` must only ever reach
    *left_controller*, and one at ``x >= left_width`` only ever
    *right_controller* — never both, never the wrong one.
    """
    if x < left_width:
        left_controller.handle_click(state, x, y)
    else:
        right_controller.handle_click(state, x - left_width, y)


def _hstack(left: Img, right: Img) -> Img:
    """Compose *left* and *right* side by side into one new ``Img`` —
    both must already be the same height."""
    combined = Img()
    combined.img = cv2.hconcat([left.img, right.img])
    return combined


def _run_single_player(
    args: argparse.Namespace,
    mapper: BoardMapper,
    board_size: "tuple[int, int]",
    asset_loader: AssetLoader,
    screen: Img,
    pending_clicks: list,
) -> None:
    """The single-window, single-mouse-stream game loop.

    *mapper* must already be constructed with the side-panel-aware
    ``x_offset``/``y_offset`` (see ``main()``) — this function itself
    just uses it via ``GraphicsBoardRenderer``/``ClickController``, same
    as every other caller, since ``BoardMapper`` is the one place that
    arithmetic belongs (see that class's own module docstring). Board,
    White's panel, and Black's panel are laid out by
    ``GraphicsBoardRenderer``'s own ``show_side_panels`` — see that
    class's docstring and ``render_player_panel``'s for the full layout
    and the bug (score text overlapping the board's own top-row pieces)
    this replaces.
    """
    quit_requested = False
    while not quit_requested:
        # Every per-game object is rebuilt fresh here, for the first game
        # and every restart alike -- see _new_game's own docstring for why
        # GameEngine specifically can't just be reused. renderer is rebuilt
        # too (fresh _piece_views, so no stale PieceView/animation state
        # carries over) but asset_loader/mapper aren't: neither holds any
        # per-game state, just already-loaded sprites and fixed geometry.
        engine, state = _new_game(args, mapper)
        renderer = GraphicsBoardRenderer(
            asset_loader, mapper, board_size=board_size, show_side_panels=True
        )
        score_tracker = ScoreTracker()
        history_tracker = MoveHistoryTracker()
        game_over_animation = GameOverAnimation()

        restart_requested = False
        last_time = time.time()

        while not restart_requested and not quit_requested:
            now = time.time()
            elapsed_ms = int((now - last_time) * 1000)
            last_time = now

            engine.tick(state, elapsed_ms)

            for x, y in pending_clicks:
                engine.handle_click(state, x, y)
            pending_clicks.clear()

            snapshot = GameSnapshot.from_state(state)
            score_tracker.update(snapshot)
            history_tracker.update(snapshot)
            game_over_animation.sync(snapshot)

            renderer.render(snapshot, screen, selected=engine.selection)
            renderer.render_player_panel(
                screen,
                Color.WHITE,
                score_tracker.get_score(Color.WHITE),
                history_tracker.moves,
            )
            renderer.render_player_panel(
                screen,
                Color.BLACK,
                score_tracker.get_score(Color.BLACK),
                history_tracker.moves,
            )
            renderer.render_game_over(
                screen, snapshot.winner, game_over_animation.progress()
            )

            # Img.show() blocks on cv2.waitKey(0) and tears the window down
            # right after — incompatible with a continuous render loop, so
            # this polls cv2 directly instead, same as the rest of this
            # pipeline.
            cv2.imshow(WINDOW_NAME, screen.img)
            key = cv2.waitKey(30)

            if key == ESC:
                quit_requested = True
            elif snapshot.game_over and key in (ord("q"), ord("Q")):
                quit_requested = True
            elif snapshot.game_over and key in (ord("r"), ord("R")):
                restart_requested = True


def _run_two_player(
    args: argparse.Namespace,
    mapper: BoardMapper,
    board_size: "tuple[int, int]",
    asset_loader: AssetLoader,
    screen: Img,
    pending_clicks: list,
    white_username: str = "White",
    black_username: str = "Black",
) -> None:
    """Split-screen two-player loop: White plays the left half, Black
    the right — one shared ``GameEngine``/``GameState`` (it's one game),
    but everything about presenting and controlling it is duplicated per
    half. See main_gui.py's design discussion (this function's sibling,
    ``_run_single_player``, and ``_OwnColorClickController``/
    ``_route_click``) for why a shared ``GameEngine.handle_click`` /
    ``engine.selection`` can't be used directly here.

    *white_username*/*black_username* label each side's score overlay
    with that player's own logged-in username (see main_gui.py's login
    flow) instead of the generic "White"/"Black" — default to those
    generic labels so this function still works standalone/untested-user
    the way it always did. Unlike single-player/hot-seat mode (one
    login, two panels, no second identity to label the other side
    with — see ``_run_single_player``/``render_player_panel``), two-player
    mode has exactly two distinct logged-in accounts, one per side.

    History panel is shown once, on the right half's own outer right
    edge (reusing ``show_history_panel`` unchanged); each half draws its
    own score overlay so neither player needs to look at the other half
    to check standings; the game-over screen is drawn once on the final
    composited canvas (``render_game_over`` depends only on its own
    arguments, not renderer instance state, so either renderer can call
    it — the right one is used here, arbitrarily).
    """
    left_width = board_size[0]

    quit_requested = False
    while not quit_requested:
        engine, state = _new_game(args, mapper)
        left_renderer = GraphicsBoardRenderer(asset_loader, mapper, board_size=board_size)
        right_renderer = GraphicsBoardRenderer(
            asset_loader, mapper, board_size=board_size, show_history_panel=True
        )
        left_controller = _OwnColorClickController(engine, mapper, Color.WHITE)
        right_controller = _OwnColorClickController(engine, mapper, Color.BLACK)

        score_tracker = ScoreTracker()
        history_tracker = MoveHistoryTracker()
        game_over_animation = GameOverAnimation()

        restart_requested = False
        last_time = time.time()

        while not restart_requested and not quit_requested:
            now = time.time()
            elapsed_ms = int((now - last_time) * 1000)
            last_time = now

            engine.tick(state, elapsed_ms)

            for x, y in pending_clicks:
                _route_click(x, y, left_width, left_controller, right_controller, state)
            pending_clicks.clear()

            snapshot = GameSnapshot.from_state(state)
            score_tracker.update(snapshot)
            history_tracker.update(snapshot)
            game_over_animation.sync(snapshot)

            white_score = score_tracker.get_score(Color.WHITE)
            black_score = score_tracker.get_score(Color.BLACK)

            left_screen = Img()
            left_renderer.render(snapshot, left_screen, selected=left_controller.selection)
            left_renderer.render_scores(
                left_screen, white_score, black_score, white_username, black_username
            )

            right_screen = Img()
            right_renderer.render(snapshot, right_screen, selected=right_controller.selection)
            right_renderer.render_scores(
                right_screen, white_score, black_score, white_username, black_username
            )
            right_renderer.render_move_history(right_screen, history_tracker.moves)

            combined = _hstack(left_screen, right_screen)
            right_renderer.render_game_over(
                combined, snapshot.winner, game_over_animation.progress()
            )
            screen.img = combined.img

            # Img.show() blocks on cv2.waitKey(0) and tears the window down
            # right after — incompatible with a continuous render loop, so
            # this polls cv2 directly instead, same as the rest of this
            # pipeline.
            cv2.imshow(WINDOW_NAME, screen.img)
            key = cv2.waitKey(30)

            if key == ESC:
                quit_requested = True
            elif snapshot.game_over and key in (ord("q"), ord("Q")):
                quit_requested = True
            elif snapshot.game_over and key in (ord("r"), ord("R")):
                restart_requested = True


class _NetworkClickController:
    """Click handling for main_gui.py's networked mode (see
    ``_run_network_player``) — tracks a LOCAL ``selection`` only (a pure
    UI/interaction concern, same principle ``GameEngine``'s own
    ``selection`` property is built on) and, on a completed selection,
    sends the move to the server instead of ever mutating a local board.

    There is no local ``GameEngine`` in this mode at all — the server is
    the sole legality authority (see network_client.py's own header and
    this feature's own brief: "the client must rely entirely on the
    server's GameEngine"). Same two-step "click a piece, click a
    destination" shape as ``ClickController``'s own selection state
    machine, and the same same-colour-switches-selection /
    anything-else-attempts-a-move rule — just against a plain
    ``AbstractBoard`` read from the latest snapshot, with no
    ``is_selectable``/busy check available (the server enforces that;
    a click on a busy piece here just becomes a move attempt the server
    will reject with an ``error``, per this feature's own spec).
    """

    def __init__(self, mapper: BoardMapper, own_color: Color) -> None:
        self._mapper = mapper
        self._own_color = own_color
        self.selection: Cell | None = None

    def handle_click(self, board: AbstractBoard, x: int, y: int, network_client: NetworkClient) -> None:
        pos = self._mapper.pixel_to_cell(x, y)
        if not board.contains(pos):
            return

        piece = board.get_piece_at(pos)
        is_own_piece = piece is not None and piece != "." and piece[0] == self._own_color.value

        if self.selection is None:
            if is_own_piece:
                self.selection = pos
            return

        if pos == self.selection:
            self.selection = None  # click the same cell again -- deselect
            return

        if is_own_piece:
            self.selection = pos  # switch to the other own piece
            return

        network_client.send_move(self.selection, pos)
        self.selection = None


def _draw_network_hud(
    screen: Img,
    username: str,
    my_color: Color,
    connected: bool,
    error_message: str,
) -> None:
    """Draw the small HUD network mode needs on top of whatever's
    already on *screen*: the logged-in player's own username/colour,
    a connection-status indicator, and the most recent error (if any
    is still within its display window — see ``_run_network_player``).
    """
    color_label = "White" if my_color is Color.WHITE else "Black"
    screen.put_text(f"You: {username} ({color_label})", 10, 20, font_size=0.5, color=(255, 255, 255, 255))

    status_text = "Connected" if connected else "Disconnected"
    status_color = (0, 200, 0, 255) if connected else (0, 0, 220, 255)
    width = screen.img.shape[1]
    screen.put_text(status_text, width - 130, 20, font_size=0.5, color=status_color)

    if error_message:
        screen.put_text(error_message, 10, screen.img.shape[0] - 15, font_size=0.5, color=(0, 0, 220, 255))


def _run_network_player(
    args: argparse.Namespace,
    mapper: BoardMapper,
    board_size: "tuple[int, int]",
    asset_loader: AssetLoader,
    screen: Img,
    pending_clicks: list,
    network_client: NetworkClient,
    my_color: Color,
    username: str,
) -> None:
    """The networked game loop: no local ``GameEngine``/``GameState`` at
    all — every bit of board truth comes from *network_client*'s most
    recently received "snapshot" message (see network_client.py's own
    header for exactly what that does and doesn't carry).

    Renders via the same ``GraphicsBoardRenderer``/``Img`` pipeline as
    local mode, but the bare board only (``show_side_panels``/
    ``show_history_panel`` both left at their default False) — no
    score or move-history tracking here: both of this codebase's
    trackers (``ScoreTracker``, ``MoveHistoryTracker``) diff
    ``GameSnapshot.pending``/``.airborne`` between frames to detect
    what happened, and the wire protocol's "snapshot" carries neither
    (see network_client.py's header) — running them against an always-
    empty ``pending``/``airborne`` would silently under-count captures
    rather than genuinely track them, so they're left out entirely
    instead of shipping a subtly-wrong approximation.

    Clicks are handled by ``_NetworkClickController``, which only
    tracks a local ``selection`` and sends a move to the server — the
    board redraws next frame from whatever snapshot the server has
    broadcast by then, which may not yet reflect a just-sent move (real
    network latency, plus this engine's own queued/real-time move
    timing — see ``GameEngine.attempt_move``'s docstring: even
    server-side, a queued move doesn't land instantly).

    Restart (R) is a no-op here — the server owns the one shared game;
    a client unilaterally restarting it isn't something this protocol
    supports yet (a later, server-side "Rooms"/rematch task, not this
    one). Q and Esc both disconnect (``network_client.close()``) and
    return.
    """
    renderer = GraphicsBoardRenderer(asset_loader, mapper, board_size=board_size)
    click_controller = _NetworkClickController(mapper, my_color)
    game_over_animation = GameOverAnimation()

    error_message = ""
    error_expires_at = 0.0

    quit_requested = False
    while not quit_requested:
        snapshot_dict = network_client.get_latest_snapshot()

        for err in network_client.pop_errors():
            error_message = err
            error_expires_at = time.time() + 4.0
        network_client.pop_events()  # not yet consumed by anything in this mode

        # "board" is checked explicitly (rather than indexed directly)
        # so a malformed/incomplete snapshot -- e.g. a future protocol
        # version, or a non-conforming server -- degrades to the
        # "waiting for the game to start" branch below instead of
        # raising KeyError and crashing this render loop.
        if snapshot_dict is not None and "board" in snapshot_dict:
            board = TextBoard(snapshot_dict["board"])

            for x, y in pending_clicks:
                click_controller.handle_click(board, x, y, network_client)
            pending_clicks.clear()

            winner_raw = snapshot_dict.get("winner")
            game_snapshot = GameSnapshot(
                board=BoardSnapshot.from_board(board),
                current_time=snapshot_dict.get("current_time", 0),
                game_over=snapshot_dict.get("game_over", False),
                winner=Color(winner_raw) if winner_raw is not None else None,
                pending=(),
                airborne=(),
            )
            renderer.render(game_snapshot, screen, selected=click_controller.selection)
            game_over_animation.sync(game_snapshot)
            renderer.render_game_over(screen, game_snapshot.winner, game_over_animation.progress())
        else:
            pending_clicks.clear()  # nothing to click on until the game starts
            screen.img = np.full((board_size[1], board_size[0], 4), NETWORK_WAITING_BGRA, dtype=np.uint8)
            screen.put_text(
                "Waiting for the game to start...",
                20, board_size[1] // 2, font_size=0.6, color=(255, 255, 255, 255),
            )

        if error_message and time.time() >= error_expires_at:
            error_message = ""
        _draw_network_hud(screen, username, my_color, network_client.is_connected(), error_message)

        # Img.show() blocks on cv2.waitKey(0) and tears the window down
        # right after — incompatible with a continuous render loop, so
        # this polls cv2 directly instead, same as the rest of this
        # pipeline.
        cv2.imshow(WINDOW_NAME, screen.img)
        key = cv2.waitKey(30)

        if key == ESC or key in (ord("q"), ord("Q")):
            quit_requested = True

    network_client.close()
