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
        * No selection, piece not in transit → piece selected.
        * No selection, piece in transit → silently ignored (cannot select
          or redirect a piece that is already mid-movement).
        * Selection exists, friendly piece not in transit → selection replaced.
        * Selection exists, friendly piece in transit → silently ignored;
          current selection is left unchanged.
        * Selection exists, empty / enemy cell:
            - Legal move  → ``PendingMove`` queued; piece stays at origin until
              ``tick`` executes the move at ``arrival_time``.  Selection cleared.
            - Illegal move → board unchanged (silent failure).  Selection cleared.

        Note: ``self.selection`` can never itself refer to an in-transit
        square — both selection paths above require ``not is_in_transit(pos)``
        before assigning — so no separate guard is needed once a selection
        is already held.
        """
        col = x // self._cell_size
        row = y // self._cell_size

        if not (0 <= row < self.board.num_rows and 0 <= col < self.board.num_cols):
            return

        pos = Position(row, col)
        clicked_piece = self.board.get_piece_at(pos)

        if self.selection is None:
            if clicked_piece != "." and not self.is_in_transit(pos):
                self.selection = pos
            return

        selected_piece = self.board.get_piece_at(self.selection)

        # Re-select a different friendly piece (skip if that piece is in transit).
        if clicked_piece != "." and self._is_friendly(selected_piece, clicked_piece):
            if not self.is_in_transit(pos):
                self.selection = pos
            return

        # Attempt move — selection always cleared after this point.
        if self._validator.is_valid(
            selected_piece, self.selection, pos, self.board
        ) and not self._route_conflicts(selected_piece, self.selection, pos):
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

    def is_in_transit(self, pos: Position) -> bool:
        """Return True if *pos* is the origin of a move that has not yet arrived."""
        return any(pm.from_pos == pos for pm in self._pending)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_friendly(piece_a: str | None, piece_b: str | None) -> bool:
        """Return True if both pieces belong to the same colour."""
        if piece_a is None or piece_b is None:
            return False
        return piece_a[0] == piece_b[0]

    @staticmethod
    def _lane(from_pos: Position, to_pos: Position) -> tuple[str, int, int] | None:
        """Return the (axis, lo, hi) lane a straight move travels through.

        A horizontal move occupies every column between ``from_pos`` and
        ``to_pos`` on its row; a vertical move occupies every row on its
        column. Diagonal / knight moves don't travel a single-axis lane and
        return ``None`` — they never participate in route locking.
        """
        if from_pos.row == to_pos.row and from_pos.col != to_pos.col:
            lo, hi = sorted((from_pos.col, to_pos.col))
            return ("col", lo, hi)
        if from_pos.col == to_pos.col and from_pos.row != to_pos.row:
            lo, hi = sorted((from_pos.row, to_pos.row))
            return ("row", lo, hi)
        return None

    def _route_conflicts(
        self, piece: str, from_pos: Position, to_pos: Position
    ) -> bool:
        """Return True if this move's lane overlaps an opposite-colour piece
        already in transit along the same lane.

        Pieces of opposite colour may not travel a common route (the same
        span of columns on a horizontal move, or rows on a vertical move)
        at the same time — the second mover is rejected. Same-colour moves
        and non-lane moves (diagonal / knight) never conflict.
        """
        lane = self._lane(from_pos, to_pos)
        if lane is None:
            return False
        axis, lo, hi = lane
        for pm in self._pending:
            if pm.piece[0] == piece[0]:
                continue
            other_lane = self._lane(pm.from_pos, pm.to_pos)
            if other_lane is None:
                continue
            other_axis, other_lo, other_hi = other_lane
            if other_axis != axis:
                continue
            if lo <= other_hi and other_lo <= hi:
                return True
        return False

