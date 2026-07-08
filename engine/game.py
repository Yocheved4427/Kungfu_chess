from __future__ import annotations

from typing import List

from core.config import MOVE_DURATION
from core.models import PendingMove, Position
from engine.board import AbstractBoard
from engine.rules import MoveValidator
from ui.events import GameEvent, MoveCompletedEvent, Observer, RenderEvent, TimeAdvancedEvent

# ---------------------------------------------------------------------------
# Kung Fu Chess – Game Engine (Iteration 6: Delayed Movement)
# ---------------------------------------------------------------------------
# New in this iteration
# ----------------------
#   * Pieces no longer move instantly.  A valid click queues a PendingMove
#     whose arrival_time = current_time + cells_moved * MOVE_DURATION
#     (Chebyshev distance: cells_moved = max(|Δrow|, |Δcol|)).
#   * tick(ms) advances the clock and flushes any due moves.
#   * Two new events: TimeAdvancedEvent and MoveCompletedEvent.
# ---------------------------------------------------------------------------


class GameEngine:
    """Core game state machine and event Subject.

    Responsibilities
    ----------------
    * Convert pixel coordinates to board cells (``handle_click``).
    * Manage single-piece selection state.
    * Validate moves via ``MoveValidator`` and queue them as ``PendingMove``.
    * Advance the game clock (``tick``); execute moves whose arrival time is due.
    * Notify registered ``Observer`` instances on ``RenderEvent``,
      ``TimeAdvancedEvent``, and ``MoveCompletedEvent``.
    """

    def __init__(
        self,
        board: AbstractBoard,
        cell_size: int = 100,
        validator: MoveValidator | None = None,
        move_duration: int = MOVE_DURATION,
    ) -> None:
        self.board: AbstractBoard = board
        self.selection: Position | None = None
        self.current_time: int = 0
        self._cell_size: int = cell_size
        self._move_duration: int = move_duration
        self._validator: MoveValidator = (
            validator if validator is not None else MoveValidator()
        )
        self._pending: List[PendingMove] = []
        self._observers: List[Observer] = []

    # ------------------------------------------------------------------
    # Subject interface
    # ------------------------------------------------------------------

    def add_observer(self, observer: Observer) -> None:
        """Register *observer* to receive future ``GameEvent`` notifications."""
        self._observers.append(observer)

    def _notify(self, event: GameEvent) -> None:
        for obs in self._observers:
            obs.on_event(event)

    def request_render(self) -> None:
        """Broadcast a ``RenderEvent`` carrying the current board text."""
        self._notify(RenderEvent(board_text=self.board.render()))

    # ------------------------------------------------------------------
    # Game commands
    # ------------------------------------------------------------------

    def handle_click(self, x: int, y: int) -> None:
        """Process a pixel-coordinate click.

        State machine
        -------------
        * Out-of-bounds click → silently ignored.
        * No selection, empty square → silently ignored.
        * No selection, piece → piece selected.
        * Selection exists, friendly piece → selection replaced.
        * Selection exists, empty / enemy cell:
            - Legal move  → ``PendingMove`` queued; piece stays at origin until
              ``tick`` executes the move at ``arrival_time``.  Selection cleared.
            - Illegal move → board unchanged (silent failure).  Selection cleared.
        """
        col = x // self._cell_size
        row = y // self._cell_size

        if not (0 <= row < self.board.num_rows and 0 <= col < self.board.num_cols):
            return

        pos = Position(row, col)
        clicked_piece = self.board.get_piece_at(pos)

        if self.selection is None:
            if clicked_piece != ".":
                self.selection = pos
            return

        selected_piece = self.board.get_piece_at(self.selection)

        # Re-select a different friendly piece.
        if clicked_piece != "." and self._is_friendly(selected_piece, clicked_piece):
            self.selection = pos
            return

        # Attempt move — selection always cleared after this point.
        if self._validator.is_valid(selected_piece, self.selection, pos, self.board):
            cells_moved = max(
                abs(self.selection.row - pos.row),
                abs(self.selection.col - pos.col),
            )
            arrival = self.current_time + cells_moved * self._move_duration
            self._pending.append(
                PendingMove(
                    piece=selected_piece,
                    from_pos=self.selection,
                    to_pos=pos,
                    arrival_time=arrival,
                )
            )
        self.selection = None

    def tick(self, ms: int) -> None:
        """Advance the game clock by *ms* milliseconds.

        After updating ``current_time``, all pending moves whose
        ``arrival_time <= current_time`` are executed in FIFO order.
        For each executed move a ``MoveCompletedEvent`` is fired.
        Finally a ``TimeAdvancedEvent`` is broadcast.
        """
        self.current_time += ms

        due: List[PendingMove] = []
        remaining: List[PendingMove] = []
        for pm in self._pending:
            (due if pm.arrival_time <= self.current_time else remaining).append(pm)
        self._pending = remaining

        for pm in due:
            # Guard: only execute if the piece is still at the origin.
            if self.board.get_piece_at(pm.from_pos) == pm.piece:
                self.board.move_piece(pm.from_pos, pm.to_pos)
                self._notify(
                    MoveCompletedEvent(
                        piece=pm.piece,
                        from_pos=pm.from_pos,
                        to_pos=pm.to_pos,
                        arrival_time=pm.arrival_time,
                    )
                )

        self._notify(TimeAdvancedEvent(current_time=self.current_time))

    # ------------------------------------------------------------------
    # Read-only accessors
    # ------------------------------------------------------------------

    @property
    def clock_ms(self) -> int:
        """Current game-clock value in milliseconds (alias for current_time)."""
        return self.current_time

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_friendly(piece_a: str | None, piece_b: str | None) -> bool:
        """Return True if both pieces belong to the same colour."""
        if piece_a is None or piece_b is None:
            return False
        return piece_a[0] == piece_b[0]

