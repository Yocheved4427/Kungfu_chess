from __future__ import annotations

import os
import pathlib
from typing import TYPE_CHECKING

from asset_loader import AssetLoader
from core.models import Position
from img import Img
from input.board_mapper import BoardMapper

if TYPE_CHECKING:
    from engine.game_state import GameState

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BOARD_PATH = REPO_ROOT / "board.png"


class GraphicsBoardRenderer:
    """Draws a ``GameState``'s board onto a window canvas via ``Img``.

    Named distinctly from ``engine.board_renderer.BoardRenderer`` (which
    returns a rendered string from a bare ``AbstractBoard``) rather than
    implementing that interface — this renderer needs the full
    ``GameState`` and produces pixels as a side effect, not a string.

    For this initial sync step every occupied cell is drawn with its
    idle state's first frame — no animation timing yet.
    """

    def __init__(self, asset_loader: AssetLoader, mapper: BoardMapper):
        self._asset_loader = asset_loader
        self._mapper = mapper
        # cv2.imread cannot open absolute paths containing non-ASCII
        # characters on Windows, so read relative to the working directory.
        self._board_template = Img().read(os.path.relpath(BOARD_PATH, start=os.getcwd()))

    def render(self, game_state: "GameState", window_img: Img) -> None:
        window_img.img = self._board_template.img.copy()

        board = game_state.board
        for row in range(board.num_rows):
            for col in range(board.num_cols):
                piece = board.get_piece_at(Position(row=row, col=col))
                if piece is None or piece == ".":
                    continue

                # Engine tokens are [color][piece] (e.g. "wK"); asset
                # folders are named [piece][color] (e.g. "KW").
                asset_code = piece[1] + piece[0].upper()
                frame = self._asset_loader.get_asset(asset_code, "idle")["frames"][0]

                x, y = self._mapper.cell_to_pixel(row, col)
                frame.draw_on(window_img, x, y)
