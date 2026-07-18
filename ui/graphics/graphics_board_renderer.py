from __future__ import annotations

from typing import TYPE_CHECKING, Dict

import cv2

from asset_loader import AssetLoader
from core.models import Position
from img import Img
from input.board_mapper import BoardMapper
from paths import REPO_ROOT
from piece_state_machine import PieceStateMachine
from piece_view import PieceView

if TYPE_CHECKING:
    from engine.snapshot import BoardSnapshot, GameSnapshot

BOARD_PATH = REPO_ROOT / "assets" / "board.png"


class GraphicsBoardRenderer:
    """Draws a ``GameSnapshot``'s board onto a window canvas via ``Img``.

    Named distinctly from ``engine.board_renderer.BoardRenderer`` (which
    returns a rendered string from a bare ``AbstractBoard``) rather than
    implementing that interface — this renderer needs the full snapshot
    and produces pixels as a side effect, not a string.

    Takes a ``GameSnapshot`` rather than a live ``GameState`` — the UI
    layer only ever reads a frozen, point-in-time view (see
    ``engine.snapshot``), never the engine's mutable internals.

    Owns one ``PieceView`` per occupied cell, kept in ``_piece_views``
    across calls (rebuilt, not recreated, each ``render()`` — see
    ``_sync_piece_views``) so each piece's ``PieceStateMachine`` keeps
    its animation timing between frames rather than restarting at frame
    0 on every render.
    """

    def __init__(self, asset_loader: AssetLoader, mapper: BoardMapper):
        self._asset_loader = asset_loader
        self._mapper = mapper
        self._piece_views: Dict[Position, PieceView] = {}
        # NOTE: passes the full absolute path directly (per explicit
        # instruction). cv2.imread cannot open absolute paths containing
        # non-ASCII characters on Windows — this will raise
        # FileNotFoundError on any machine where the repo path itself
        # contains such characters (e.g. this one).
        self._board_template = Img().read(BOARD_PATH)

    def render(self, game_snapshot: "GameSnapshot", window_img: Img) -> None:
        window_img.img = self._board_template.img.copy()

        self._sync_piece_views(game_snapshot.board)

        cell_size = self._mapper.cell_size
        for position, view in self._piece_views.items():
            frame = view.get_current_frame()

            # Sprites are stored at their native resolution, which does
            # not generally match the board's cell size, so scale a
            # copy rather than mutating (and thereby corrupting) the
            # cached frame that other cells/renders will reuse.
            scaled = Img()
            scaled.img = cv2.resize(
                frame.img, (cell_size, cell_size), interpolation=cv2.INTER_AREA
            )

            x, y = self._mapper.cell_to_pixel(position.row, position.col)
            scaled.draw_on(window_img, x, y)

    def render_scores(
        self, window_img: Img, white_score: int, black_score: int
    ) -> None:
        """Draw both players' cumulative capture scores in the top
        corners of *window_img* — White top-left, Black top-right.

        A separate call from ``render()`` rather than folded into it:
        ``render()``'s contract (one ``GameSnapshot`` in, the board drawn)
        stays unchanged for every existing caller/test, and the score
        display is a simple, independent overlay — no per-piece view or
        animation state involved, just two ``Img.put_text`` calls.
        """
        white_x, white_y = 10, 30
        black_text = f"Black: {black_score}"
        # Right-aligned against the window's own width rather than a
        # fixed offset, so it stays in the corner regardless of board size.
        black_x = window_img.img.shape[1] - 10 - len(black_text) * 17
        black_y = 30

        window_img.put_text(f"White: {white_score}", white_x, white_y, font_size=0.8)
        window_img.put_text(black_text, black_x, black_y, font_size=0.8)

    def _sync_piece_views(self, board: "BoardSnapshot") -> None:
        """Rebuild ``_piece_views`` for *board*'s current occupancy.

        A cell whose piece is unchanged from the last sync reuses (and
        syncs) its existing ``PieceView``, so its animation timing
        carries over. A cell that's newly occupied — including one
        whose previous occupant was just captured, since the capturing
        piece overwrites that cell's token rather than leaving it
        briefly empty — gets a fresh ``PieceView`` starting at "idle".
        A ``PieceView`` for a cell that's no longer occupied is simply
        not carried into the new collection (dropped).
        """
        new_views: Dict[Position, PieceView] = {}
        for row in range(board.num_rows):
            for col in range(board.num_cols):
                position = Position(row=row, col=col)
                piece = board.get_piece_at(position)
                if piece is None:
                    continue

                existing = self._piece_views.get(position)
                if (
                    existing is not None
                    and existing.snapshot is not None
                    and existing.snapshot.color == piece.color
                    and existing.snapshot.kind == piece.kind
                ):
                    view = existing
                else:
                    # Engine tokens (e.g. "wK") and pieces3 asset folder
                    # names use the same [color][piece] convention, so no
                    # translation is needed here (unlike the old
                    # pieces1/pieces2 layout).
                    token = piece.color.value + piece.kind
                    states = self._asset_loader.load(token)
                    view = PieceView(PieceStateMachine(states, start_state="idle"))

                view.sync(piece)
                new_views[position] = view

        self._piece_views = new_views
