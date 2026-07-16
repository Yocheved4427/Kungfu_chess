from __future__ import annotations

from typing import TYPE_CHECKING

import cv2

from asset_loader import AssetLoader
from core.models import Position
from img import Img
from input.board_mapper import BoardMapper
from paths import REPO_ROOT

if TYPE_CHECKING:
    from engine.game_state import GameState

BOARD_PATH = REPO_ROOT / "assets" / "board.png"


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
        # NOTE: passes the full absolute path directly (per explicit
        # instruction). cv2.imread cannot open absolute paths containing
        # non-ASCII characters on Windows — this will raise
        # FileNotFoundError on any machine where the repo path itself
        # contains such characters (e.g. this one).
        self._board_template = Img().read(BOARD_PATH)

    def render(self, game_state: "GameState", window_img: Img) -> None:
        window_img.img = self._board_template.img.copy()

        board = game_state.board
        for row in range(board.num_rows):
            for col in range(board.num_cols):
                piece = board.get_piece_at(Position(row=row, col=col))
                if piece is None or piece == ".":
                    continue

                # Engine tokens (e.g. "wK") and pieces3 asset folder names
                # use the same [color][piece] convention, so no translation
                # is needed here (unlike the old pieces1/pieces2 layout).
                frame = self._asset_loader.get_asset(piece, "idle")["frames"][0]

                # Sprites are stored at their native resolution, which does
                # not generally match the board's cell size, so scale a
                # copy rather than mutating (and thereby corrupting) the
                # cached frame that other cells/renders will reuse.
                cell_size = self._mapper.cell_size
                scaled = Img()
                scaled.img = cv2.resize(
                    frame.img, (cell_size, cell_size), interpolation=cv2.INTER_AREA
                )

                x, y = self._mapper.cell_to_pixel(row, col)
                scaled.draw_on(window_img, x, y)
