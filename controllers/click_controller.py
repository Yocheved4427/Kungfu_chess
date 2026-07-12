from __future__ import annotations

from typing import TYPE_CHECKING

from core.models import Position
from engine.board_mapper import BoardMapper

if TYPE_CHECKING:
    from engine.game import GameEngine

# ---------------------------------------------------------------------------
# Kung Fu Chess – Click Controller
# ---------------------------------------------------------------------------
# Decides what a click MEANS — select a piece, switch selection to a
# different friendly piece, or attempt to move the selected piece — and
# nothing more. It never decides whether a move is legal: every move
# attempt is forwarded to GameEngine.try_move(), and this class only
# reacts to the MoveResult by clearing selection — it never inspects it.
# Selection is cleared either way (OK or any rejection) — this controller
# doesn't know or care why an attempt failed.
#
# GameEngine remains the sole legality authority (RuleEngine's per-piece
# IPieceRule strategies, plus the busy/in-transit/airborne check behind
# is_selectable()). This class owns only: pixel -> cell translation (via
# BoardMapper) and the selection state machine that interprets a
# sequence of clicks.
#
# NOTE — try_move() applies a legal move to the board IMMEDIATELY (no
# queueing, no arrival_time, no waiting on tick()). Clicking a piece and
# then a destination now moves it instantly. The engine's older
# real-time pipeline (attempt_move -> PendingMove -> tick(), with
# transit-lock, the opposite-colour route lock, and jump-interception)
# still exists and is still fully functional — but it is no longer
# reachable through handle_click; call attempt_move()/tick() directly to
# use it.
# ---------------------------------------------------------------------------


class ClickController:
    """Interprets clicks against a ``GameEngine``.

    Click semantics
    ----------------
    * No selection, click on a selectable piece -> select it.
    * No selection, click on an empty cell (or a busy piece) -> no-op.
    * Selection held, click on a different, selectable friendly piece ->
      selection switches to it (not a move attempt).
    * Selection held, click anywhere else -> forwarded to
      ``GameEngine.try_move``, which validates via ``RuleEngine`` and,
      if the result is ``MoveResult.OK``, applies the move to the board
      immediately. Selection is cleared afterward regardless of the
      result.
    * Game over -> every click is a no-op.
    """

    def __init__(self, engine: "GameEngine", mapper: BoardMapper) -> None:
        self._engine = engine
        self._mapper = mapper
        self.selection: Position | None = None

    def handle_click(self, x: int, y: int) -> None:
        if self._engine.game_over:
            return

        pos = self._mapper.pixel_to_cell(x, y)
        board = self._engine.board
        if not (0 <= pos.row < board.num_rows and 0 <= pos.col < board.num_cols):
            return

        clicked_piece = board.get_piece_at(pos)

        if self.selection is None:
            if clicked_piece != "." and self._engine.is_selectable(pos):
                self.selection = pos
            return

        selected_piece = board.get_piece_at(self.selection)

        # A click on a different friendly, selectable piece switches the
        # selection — it is never treated as a move attempt.
        if clicked_piece != "." and self._is_friendly(selected_piece, clicked_piece):
            if self._engine.is_selectable(pos):
                self.selection = pos
            return

        # Anything else — empty cell or enemy piece — is a move attempt.
        # This controller does not decide whether it's legal; it just
        # forwards it and clears the selection no matter the outcome.
        self._engine.try_move(self.selection, pos)
        self.selection = None

    @staticmethod
    def _is_friendly(piece_a: str | None, piece_b: str | None) -> bool:
        """Return True if both pieces belong to the same colour."""
        if piece_a is None or piece_b is None:
            return False
        return piece_a[0] == piece_b[0]
