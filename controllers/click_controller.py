from __future__ import annotations

from typing import TYPE_CHECKING

from core.models import Position, same_color
from input.board_mapper import BoardMapper

if TYPE_CHECKING:
    from engine.game import GameEngine
    from engine.game_state import GameState

# ---------------------------------------------------------------------------
# Kung Fu Chess – Click Controller
# ---------------------------------------------------------------------------
# Decides what a click MEANS — select a piece, switch selection to a
# different friendly piece, or attempt to move the selected piece — and
# nothing more. It never decides whether a move is legal: every move
# attempt is forwarded to GameEngine.attempt_move(), and this class only
# reacts to the True/False result by clearing selection — it never
# inspects it. Selection is cleared either way (queued or rejected) —
# this controller doesn't know or care why an attempt failed.
#
# GameEngine remains the sole legality authority (MoveValidator, the
# opposite-colour route lock, and the busy/in-transit/airborne check
# behind is_selectable()/attempt_move()). This class owns only: pixel ->
# cell translation (via BoardMapper) and the selection state machine
# that interprets a sequence of clicks.
#
# NOTE — attempt_move() QUEUES a legal move as a PendingMove; the piece
# only relocates later, once GameEngine.tick() reaches the move's
# arrival_time (Chebyshev distance * move_duration). This is the
# real-time pipeline (Iteration 6): transit-lock, the opposite-colour
# route lock, and jump-interception all apply. GameEngine.try_move (a
# separate, synchronous, RuleEngine-backed API that applies a move
# instantly) still exists and is still fully functional — but clicks do
# not use it.
#
# NOTE — GameEngine is stateless (Iteration 15): handle_click takes the
# game's ``GameState`` as an explicit argument and forwards it to
# is_selectable()/attempt_move() on every call. This class still holds a
# reference to the ``GameEngine`` instance (to call into it) and to its
# own ``selection`` (a UI/interaction concern with no GameState field of
# its own) — but never a ``GameState`` reference; it only ever sees one
# for the duration of a single handle_click() call.
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
      ``GameEngine.attempt_move``, which validates the move and, if
      legal, queues it as a ``PendingMove`` — it does not relocate the
      piece immediately; that happens later via ``tick()``. Selection is
      cleared afterward regardless of the result.
    * Game over -> every click is a no-op.
    """

    def __init__(self, engine: "GameEngine", mapper: BoardMapper) -> None:
        self._engine = engine
        self._mapper = mapper
        self.selection: Position | None = None

    def handle_click(self, state: "GameState", x: int, y: int) -> None:
        if state.game_over:
            return

        pos = self._mapper.pixel_to_cell(x, y)
        board = state.board
        if not board.contains(pos):
            return

        clicked_piece = board.get_piece_at(pos)

        if self.selection is None:
            if clicked_piece != "." and self._engine.is_selectable(state, pos):
                self.selection = pos
            return

        selected_piece = board.get_piece_at(self.selection)

        # A click on a different friendly, selectable piece switches the
        # selection — it is never treated as a move attempt.
        if clicked_piece != "." and same_color(selected_piece, clicked_piece):
            if self._engine.is_selectable(state, pos):
                self.selection = pos
            return

        # Anything else — empty cell or enemy piece — is a move attempt.
        # This controller does not decide whether it's legal; it just
        # forwards it and clears the selection no matter the outcome.
        self._engine.attempt_move(state, self.selection, pos)
        self.selection = None
