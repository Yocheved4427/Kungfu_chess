from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Sequence

import cv2

from asset_loader import AssetLoader
from core.models import Color, Position
from img import Img
from input.board_mapper import BoardMapper
from paths import REPO_ROOT
from piece_state_machine import PieceStateMachine
from piece_view import PieceView

if TYPE_CHECKING:
    from engine.move_history_tracker import CompletedMove
    from engine.snapshot import BoardSnapshot, GameSnapshot, PieceSnapshot

BOARD_PATH = REPO_ROOT / "assets" / "board.png"

# Pixel width of the reserved history-panel region (see
# GraphicsBoardRenderer.__init__'s show_history_panel) and the solid
# background colour (BGRA) it's filled with -- a dark near-black, distinct
# from the board itself so the panel reads as a separate region.
HISTORY_PANEL_WIDTH_PX = 220
HISTORY_PANEL_BACKGROUND_BGRA = (30, 30, 30, 255)

# BGR (no alpha -- alpha varies per frame with the fade, set separately
# in render_game_over) of the game-over dark overlay.
GAME_OVER_OVERLAY_BGR = (20, 20, 20)


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

    def __init__(
        self,
        asset_loader: AssetLoader,
        mapper: BoardMapper,
        board_size: "tuple[int, int] | None" = None,
        show_history_panel: bool = False,
    ):
        """
        *board_size*, if given, is ``(width_px, height_px)`` — the
        background board image is stretched to exactly this size rather
        than kept at its native resolution, so it agrees with *mapper*'s
        own ``cell_size`` (``mapper.cell_size * num_cols/num_rows``) —
        this project's rule that rendering and click-to-cell mapping
        must share one source of truth for cell size (see
        ``input.board_mapper``'s own module docstring) applies to the
        background image too, not just piece sprites. ``None`` (the
        default) keeps today's behaviour exactly: the board image at its
        native pixel size, whatever that happens to be.

        *show_history_panel*, if True, makes ``render()`` reserve
        ``HISTORY_PANEL_WIDTH_PX`` extra pixels to the RIGHT of the board
        (see ``render()``) for ``render_move_history()`` to draw into.
        Defaults to False so every existing caller/test keeps working
        unchanged — the reserved region only ever appears at the board's
        right edge, never shifting the board's own pixels (which start
        at (0, 0) either way), so click-to-cell mapping via *mapper*
        needs no changes: a click landing in the panel simply maps to a
        column past ``num_cols``, which ``AbstractBoard.contains``
        already rejects as a no-op, same as any other out-of-bounds click.
        """
        self._asset_loader = asset_loader
        self._mapper = mapper
        self._show_history_panel = show_history_panel
        self._piece_views: Dict[Position, PieceView] = {}
        # NOTE: passes the full absolute path directly (per explicit
        # instruction). cv2.imread cannot open absolute paths containing
        # non-ASCII characters on Windows — this will raise
        # FileNotFoundError on any machine where the repo path itself
        # contains such characters (e.g. this one).
        self._board_template = Img().read(BOARD_PATH, size=board_size)

    def render(
        self,
        game_snapshot: "GameSnapshot",
        window_img: Img,
        selected: Position | None = None,
    ) -> None:
        """Draw *game_snapshot*'s board, plus a "SEL" label over the cell
        at *selected* (if any) and a remaining-cooldown label over any
        piece still cooling down.

        *selected* is a separate parameter, not part of *game_snapshot*,
        because the current selection isn't part of ``GameState`` at all
        — it's owned by ``ClickController`` (see that module's own
        header comment) and only reachable via ``GameEngine.selection``.
        Defaults to ``None`` so every existing caller/test keeps working
        unchanged.
        """
        if self._show_history_panel:
            window_img.img = cv2.copyMakeBorder(
                self._board_template.img,
                0, 0, 0, HISTORY_PANEL_WIDTH_PX,
                cv2.BORDER_CONSTANT,
                value=HISTORY_PANEL_BACKGROUND_BGRA,
            )
        else:
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

            piece = game_snapshot.board.get_piece_at(position)
            self._draw_overlay_label(window_img, piece, position == selected, x, y)

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
        # Right-aligned against the BOARD's own width specifically (not
        # window_img's, which is wider than the board whenever
        # show_history_panel reserves extra space to the right) so this
        # stays anchored to the board's own top-right corner regardless
        # of whether a history panel is present.
        board_width = self._board_template.img.shape[1]
        black_x = board_width - 10 - len(black_text) * 17
        black_y = 30

        window_img.put_text(f"White: {white_score}", white_x, white_y, font_size=0.8)
        window_img.put_text(black_text, black_x, black_y, font_size=0.8)

    def render_move_history(
        self,
        window_img: Img,
        moves: "Sequence[CompletedMove]",
        max_entries: int = 16,
    ) -> None:
        """Draw the most recent completed moves into the history panel
        reserved by ``show_history_panel=True`` at construction.

        A separate call from ``render()``, same reasoning as
        ``render_scores``: an independent overlay, not part of
        ``render()``'s own per-piece drawing. A no-op if
        ``show_history_panel`` was False at construction — there's no
        reserved region to draw into, and *window_img* is exactly the
        board's own width in that case, so text here would either land
        off-canvas or overwrite the board itself.

        Only the last *max_entries* moves are drawn (oldest of that
        slice at the top), not the whole (potentially long) history —
        "truncated list of recent moves", per this feature's own brief.
        White's moves and Black's are drawn in different colours so the
        two are visually distinguishable at a glance.
        """
        if not self._show_history_panel:
            return

        panel_x = self._board_template.img.shape[1] + 10
        y = 25
        window_img.put_text("History", panel_x, y, font_size=0.6, color=(255, 255, 255, 255))
        y += 25

        for move in moves[-max_entries:]:
            color = (255, 255, 255, 255) if move.color is Color.WHITE else (0, 215, 255, 255)
            seconds = move.time / 1000
            text = f"{seconds:6.1f}s {move.kind}->({move.destination.row},{move.destination.col})"
            window_img.put_text(text, panel_x, y, font_size=0.42, color=color)
            y += 18

    def render_game_over(
        self,
        window_img: Img,
        winner: "Color | None",
        progress: float,
    ) -> None:
        """Draw the animated game-over screen: a dark overlay fading in
        over *window_img*, plus "GAME OVER" and the winner (or "Draw"),
        driven by *progress* (0.0..1.0 — see
        ``ui.graphics.game_over_animation.GameOverAnimation``).

        A no-op while *progress* is 0 (the game hasn't ended yet, or the
        animation genuinely hasn't advanced at all — either way there's
        nothing to draw). *progress* is expected to only ever increase
        and then hold at 1.0 once the game has ended; this method itself
        has no memory of past frames — it just draws whatever fraction
        it's given, same "separate compute vs. draw" split as
        ``render_scores``/``render_move_history`` (the tracker computes,
        this only draws).

        The overlay's fade uses ``Img.draw_on``'s existing alpha-channel
        blending (already proven elsewhere in this codebase, e.g. piece
        sprites with transparent backgrounds) rather than any new
        blending logic: a copy of *window_img* is flooded with
        ``GAME_OVER_OVERLAY_BGR`` at alpha ``round(255 * progress)`` via
        ``cv2.rectangle`` (avoiding a new ``numpy`` import in this file,
        same reasoning as ``render()``'s ``cv2.copyMakeBorder`` for the
        history panel), then drawn back onto *window_img* — a uniform
        alpha across every pixel fades the WHOLE overlay in together.
        Text is drawn on top at full opacity every frame once progress
        is nonzero; only the background darkens over time, not the text
        itself (simplest effect that's still clearly time-based, per
        this feature's own brief).
        """
        if progress <= 0:
            return

        h, w = window_img.img.shape[:2]
        overlay = Img()
        overlay.img = window_img.img.copy()
        alpha = round(255 * progress)
        cv2.rectangle(overlay.img, (0, 0), (w, h), (*GAME_OVER_OVERLAY_BGR, alpha), -1)
        overlay.draw_on(window_img, 0, 0)

        winner_text = "Draw" if winner is None else f"{winner.name.title()} wins!"
        text_x = max(w // 2 - 100, 0)
        text_y = h // 2
        window_img.put_text(
            "GAME OVER", text_x, text_y, font_size=1.1, color=(255, 255, 255, 255), thickness=2
        )
        window_img.put_text(
            winner_text, text_x, text_y + 40, font_size=0.8, color=(255, 255, 255, 255)
        )

    def _draw_overlay_label(
        self,
        window_img: Img,
        piece: "PieceSnapshot | None",
        is_selected: bool,
        x: int,
        y: int,
    ) -> None:
        """Draw at most one small text label just above the cell at
        pixel (*x*, *y*) — "SEL" if this is the selected cell, or the
        piece's remaining cooldown time otherwise.

        The two never overlap in practice: ``ClickController``/
        ``GameEngine.is_selectable`` never allow a piece that's busy
        (mid-move, airborne, or cooling down — see
        ``GameEngine._is_busy``) to become the selection, so a selected
        piece can never also be in cooldown. Selection is still checked
        first here regardless, since it needs no ``piece`` at all (an
        empty cell can't be selected either way, but there's no reason
        to couple the two checks).
        """
        label_x, label_y = x + 2, y - 6
        if is_selected:
            window_img.put_text("SEL", label_x, label_y, font_size=0.4, color=(0, 255, 255, 255))
            return

        if piece is not None and piece.cooldown_remaining_ms is not None:
            seconds = piece.cooldown_remaining_ms / 1000
            window_img.put_text(
                f"{seconds:.1f}s", label_x, label_y, font_size=0.4, color=(0, 165, 255, 255)
            )

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
