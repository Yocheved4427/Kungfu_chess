from __future__ import annotations

from typing import List, Tuple

import cv2

# ---------------------------------------------------------------------------
# Kung Fu Chess -- Mouse/keyboard event handling for the local game window
# ---------------------------------------------------------------------------
# Wraps the raw cv2 mouse-callback + waitKey polling every local render
# loop in this codebase already did inline (see the original
# ui/game_loop.py's `on_mouse`/`pending_clicks` pattern, still used
# as-is by main_gui.py's own networked/hybrid loop) as one small,
# reusable, testable class -- this is purely I/O plumbing (translating
# a raw OS click/keypress into "a click happened at (x, y)" / "a known
# key was pressed"); it has no opinion on what a click or key MEANS,
# same separation ClickController (controllers/click_controller.py)
# already draws between click semantics and pixel<->cell translation.
# ---------------------------------------------------------------------------

ESC = 27
KEY_QUIT = (ord("q"), ord("Q"))
KEY_RESTART = (ord("r"), ord("R"))


class InputHandler:
    """Collects left-clicks on one named cv2 window and polls key presses.

    Construct once per window (``cv2.namedWindow(window_name)`` must
    already have been called), then call ``poll_clicks()`` once per
    render-loop iteration to drain whatever clicks arrived since the
    last poll, and ``poll_key(wait_ms)`` to both pump the cv2 event
    loop (required for the window to repaint/respond at all) and read
    the next key press, if any.
    """

    def __init__(self, window_name: str) -> None:
        self._clicks: List[Tuple[int, int]] = []
        cv2.setMouseCallback(window_name, self._on_mouse)

    def _on_mouse(self, event: int, x: int, y: int, flags: int, param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            self._clicks.append((x, y))

    def poll_clicks(self) -> List[Tuple[int, int]]:
        """Return every click collected since the last call, then clear
        the queue -- each click is delivered exactly once."""
        clicks = self._clicks
        self._clicks = []
        return clicks

    def poll_key(self, wait_ms: int = 30) -> int:
        """Pump the cv2 event loop for *wait_ms* and return the key
        pressed during that window, or -1 if none was."""
        return cv2.waitKey(wait_ms)

    @staticmethod
    def is_quit(key: int, game_over: bool) -> bool:
        """True if *key* should end the render loop entirely -- Esc
        always quits; Q only once the game has actually ended (mirrors
        the on-screen "Press R to play again, Q to quit" hint, which
        only appears post-game-over)."""
        return key == ESC or (game_over and key in KEY_QUIT)

    @staticmethod
    def is_restart(key: int, game_over: bool) -> bool:
        """True if *key* should start a fresh game -- only reachable
        once the current one has ended, same as ``is_quit``'s Q case."""
        return game_over and key in KEY_RESTART
