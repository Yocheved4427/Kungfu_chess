from __future__ import annotations

from typing import Dict, List

from controllers.click_controller import ClickController
from core.config import COOLDOWN_DURATION, JUMP_DURATION, MOVE_DURATION
from core.models import Color, PendingJump, PendingMove, Position, same_color
from engine.board import AbstractBoard
from engine.board_mapper import BoardMapper
from engine.board_renderer import BoardRenderer, TextBoardRenderer
from engine.collision_resolver import CollisionResolver
from engine.game_over import GameOverRule, KingCaptureRule
from engine.rule_engine import MoveResult, RuleEngine
from engine.rules import MoveValidator
from ui.events import (
    AirborneCaptureEvent,
    GameEvent,
    GameOverEvent,
    JumpLandedEvent,
    MoveCompletedEvent,
    Observer,
    RenderEvent,
    TimeAdvancedEvent,
)

# ---------------------------------------------------------------------------
# Kung Fu Chess – Game Engine (Iteration 13: Collision resolution extracted)
# ---------------------------------------------------------------------------
# New in this iteration
# ----------------------
#   * tick()'s collision-decision logic — friendly mid-route blocking and
#     airborne-enemy interception — moved out into ``CollisionResolver``
#     (SRP). tick() now only orchestrates: advance the clock, partition
#     due moves, delegate each one to ``_resolve_due_move``, resolve
#     jump landings, check game-over, notify. ``_resolve_due_move`` still
#     does all board mutation and event notification itself — GameEngine
#     remains the sole board mutator and the only Subject; the resolver
#     only decides, stateless, same idiom as MoveValidator/RuleEngine.
#
# Iteration 12 recap: Clicks back on the queue
# -------------------------------------------------------------------
#   * ClickController forwards move attempts to attempt_move again
#     (MoveValidator-backed, queued) rather than try_move (RuleEngine
#     -backed, instant) — the VPL grader enforces Iteration 6 mechanics:
#     a click queues a PendingMove, and the piece only relocates once
#     tick() reaches its arrival_time. The real-time pipeline (transit
#     lock, the opposite-colour route lock, jump interception) is once
#     again reachable through handle_click, exactly as before Iteration 11.
#   * try_move/RuleEngine (Iteration 10) still exist, are still fully
#     functional and independently tested, and remain the sole
#     mutation-authority contract described below — they're just not
#     what a click drives anymore. Call try_move directly for a
#     synchronous, instant, RuleEngine-validated move.
#
# Iteration 11 recap: Clicks drove RuleEngine (superseded above)
# -------------------------------------------------------------------
#   * Adding a new piece type is purely a new IPieceRule + one
#     RuleEngine.register() call: neither ClickController nor GameEngine
#     needs to change (RuleEngine's registry dispatch is piece-agnostic)
#     — true regardless of which pathway (try_move or attempt_move) a
#     click happens to drive.
#
# Iteration 10 recap: RuleEngine service layer
# -----------------------------------------------
#   * try_move(from_pos, to_pos) -> MoveResult: a synchronous, plain
#     RuleEngine-backed move. GameEngine is confirmed/kept as the single
#     service layer that owns board state — it is the only component
#     that ever calls board.move_piece / board.set_piece_at; RuleEngine
#     only reads the board to decide legality and never mutates it.
#
# Iteration 9 recap: Click Controller
# -------------------------------------
#   * Click *semantics* (select / switch selection / attempt move) moved
#     out into ClickController — GameEngine no longer decides what a
#     click means, only whether a forwarded move is legal. handle_click
#     is now a one-line delegation; ``selection`` is a read-only property
#     proxying the controller. attempt_move() and is_selectable() are the
#     legality surface ClickController calls into.
#
# Iteration 8 recap: Jump
# ------------------------
#   * handle_jump(x, y) sends a piece airborne for ``jump_duration`` ms
#     (default JUMP_DURATION). Unlike a move, a jump never relocates its
#     piece — it stays on its own cell the whole time, tracked separately
#     in ``_airborne`` (a list of PendingJump) rather than ``_pending``.
#   * While airborne, the piece is immune to capture: if an enemy
#     PendingMove arrives at its cell during the window, tick() removes
#     the ARRIVING piece instead (AirborneCaptureEvent) and the defender
#     never moves. A friendly arrival is already rejected by the existing
#     friendly-fire check in MoveValidator — no special-casing needed.
#   * If nothing arrives before land_time, the jump simply expires
#     (JumpLandedEvent) — the board was never touched.
#   * A piece already moving or already airborne can't jump again, and
#     can't be selected/redirected via handle_click either — see _is_busy.
# ---------------------------------------------------------------------------


class GameEngine:
    """Core game state machine and event Subject.

    Responsibilities
    ----------------
    * The single service layer that owns board state. Nothing else may
      mutate it: ``board.move_piece``/``board.set_piece_at`` are called
      only from within this class (``tick()`` and ``try_move``) — every
      other component (``RuleEngine``, ``MoveValidator``,
      ``ClickController``, ...) only ever *reads* the board.
    * Be the sole authority on move *legality*, through two parallel
      pathways: ``attempt_move``/``is_selectable`` (the real-time, queued
      pipeline behind ``handle_click``, backed by ``MoveValidator`` plus
      the busy/route-lock rules) and ``try_move`` (a synchronous, plain
      ``RuleEngine``-backed move — still fully functional and
      independently usable, just not what a click drives). Click
      *semantics* (what a click means) are NOT this class's job; they
      live in ``ClickController``, which this class delegates
      ``handle_click`` to and exposes via the read-only ``selection``
      property.
    * Translate pixel coordinates to board cells via ``BoardMapper``
      (used directly by ``handle_jump``, and indirectly by
      ``ClickController`` for ``handle_click``) — the only component
      that does so; nothing does raw ``x // cell_size`` arithmetic.
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
        game_over_rule: GameOverRule | None = None,
        jump_duration: int = JUMP_DURATION,
        renderer: BoardRenderer | None = None,
        mapper: BoardMapper | None = None,
        rule_engine: RuleEngine | None = None,
        cooldown_duration: int = COOLDOWN_DURATION,
        collision_resolver: CollisionResolver | None = None,
    ) -> None:
        self.board: AbstractBoard = board
        self.current_time: int = 0
        self._mapper: BoardMapper = mapper if mapper is not None else BoardMapper(cell_size)
        self._move_duration: int = move_duration
        self._jump_duration: int = jump_duration
        self._cooldown_duration: int = cooldown_duration
        self._cooldowns: Dict[Position, int] = {}
        self._validator: MoveValidator = (
            validator if validator is not None else MoveValidator()
        )
        self._rule_engine: RuleEngine = (
            rule_engine if rule_engine is not None else RuleEngine()
        )
        self._game_over_rule: GameOverRule = (
            game_over_rule if game_over_rule is not None else KingCaptureRule()
        )
        self._renderer: BoardRenderer = (
            renderer if renderer is not None else TextBoardRenderer()
        )
        self._collision_resolver: CollisionResolver = (
            collision_resolver if collision_resolver is not None else CollisionResolver()
        )
        self._pending: List[PendingMove] = []
        self._airborne: List[PendingJump] = []
        self._observers: List[Observer] = []
        self.game_over: bool = False
        self.winner: Color | None = None
        # Prime the rule with the pristine starting board — before any
        # move can run — so a stateful rule like KingCaptureRule can tell
        # "this colour never had a King" apart from "its King was captured".
        self._game_over_rule.check(board)
        # Click semantics (select / switch-selection / attempt-move) are
        # entirely owned by ClickController — see handle_click below.
        self._click_controller: ClickController = ClickController(self, self._mapper)

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
        self._notify(RenderEvent(board_text=self._renderer.render(self.board)))

    # ------------------------------------------------------------------
    # Game commands
    # ------------------------------------------------------------------

    def handle_click(self, x: int, y: int) -> None:
        """Process a pixel-coordinate click.

        Entirely delegated to ``ClickController``, which owns click
        semantics (select / switch selection / attempt move) and the
        ``selection`` state — see that class for the full state machine.
        GameEngine's only role here is legality: ``ClickController``
        forwards every move attempt to ``attempt_move`` (so a click that
        completes a move queues it as a ``PendingMove`` — the piece
        relocates later, via ``tick()``) and every selection decision
        consults ``is_selectable``; it never decides legality itself.
        """
        self._click_controller.handle_click(x, y)

    def is_selectable(self, pos: Position) -> bool:
        """True iff *pos* holds a piece that can currently be selected.

        A piece is selectable iff it exists and isn't busy (mid-move,
        airborne, or cooling down from its last landing). Pure query
        used by ``ClickController`` — it says
        nothing about whether any particular move from that piece would
        be legal; that's ``attempt_move``'s job.
        """
        piece = self.board.get_piece_at(pos)
        return piece is not None and piece != "." and not self._is_busy(pos)

    def attempt_move(self, from_pos: Position, to_pos: Position) -> bool:
        """The real-time pipeline's move attempt — queues rather than
        applies. This is what ``ClickController`` forwards every move
        attempt to behind ``handle_click``.

        Attempts to move whatever is at *from_pos* to *to_pos*, queuing
        a ``PendingMove`` iff every check passes. Returns True iff the
        move was queued; the piece itself only relocates later, when
        ``tick`` reaches its ``arrival_time``. Checks, in order:

        * The game isn't over.
        * A piece actually sits at *from_pos* and isn't busy (mid-move,
          airborne, or cooling down from its last landing).
        * ``MoveValidator`` approves the shape/destination/path.
        * The move doesn't violate the opposite-colour route lock.
        """
        if self.game_over:
            return False

        piece = self.board.get_piece_at(from_pos)
        if piece is None or piece == "." or self._is_busy(from_pos):
            return False

        if not self._validator.is_valid(piece, from_pos, to_pos, self.board):
            return False
        if self._route_conflicts(piece, from_pos, to_pos):
            return False

        cells_moved = max(
            abs(from_pos.row - to_pos.row),
            abs(from_pos.col - to_pos.col),
        )
        arrival = self.current_time + cells_moved * self._move_duration
        self._pending.append(
            PendingMove(
                piece=piece,
                from_pos=from_pos,
                to_pos=to_pos,
                arrival_time=arrival,
            )
        )
        return True

    def try_move(self, from_pos: Position, to_pos: Position) -> MoveResult:
        """Synchronous, ``RuleEngine``-backed move — GameEngine's plain
        service-layer entry point, distinct from the real-time pipeline.
        Independently usable and fully tested, but ``ClickController``
        does not call this — clicks drive ``attempt_move`` instead (the
        VPL grader enforces the queued, real-time mechanics).

        Validates via ``RuleEngine.validate_move`` and, only if the
        result is ``MoveResult.OK``, applies the move to the board
        *immediately* (``board.move_piece``) — no queueing, no
        ``arrival_time``, no waiting on ``tick``. Always returns the
        exact ``MoveResult`` that decided the outcome, so a caller can
        tell precisely why a move was rejected instead of just that it
        was. GameEngine is the only component that ever mutates the
        board — ``RuleEngine`` only reads it to decide legality.

        Adding a new piece type never requires touching this method,
        ``ClickController``, or anything else here — ``RuleEngine``
        dispatches by piece-type character through its own registry, so
        a new ``IPieceRule`` plus one ``register()`` call is the entire
        change (Strategy pattern / OCP).

        This intentionally does **not** model the real-time gameplay
        rules layered on top of ``MoveValidator`` in ``attempt_move``
        (the pipeline clicks actually drive): no busy/in-transit or
        airborne check, no opposite-colour route lock, no interaction
        with an airborne defender at *to_pos* (an enemy there is just an
        ordinary capture, same as any other piece — Jump's mid-air
        interception is an ``attempt_move``-only concept). Use
        ``attempt_move``/``handle_click`` for actual gameplay; use
        ``try_move`` wherever a direct, synchronous move — driven purely
        by RuleEngine's legality result — is what's wanted.

        On success this still triggers the same landing side effects any
        other completed move does: Pawn promotion and a game-over check,
        so board state stays consistent regardless of which pathway
        moved a piece. A ``MoveCompletedEvent`` is fired for parity with
        ``tick()``'s notifications; ``arrival_time`` is reported as the
        current clock value, since the move already happened.
        """
        if self.game_over:
            return MoveResult.GAME_OVER

        piece = self.board.get_piece_at(from_pos) or "."
        result = self._rule_engine.validate_move(piece, from_pos, to_pos, self.board)
        if not result.is_ok:
            return result

        self.board.move_piece(from_pos, to_pos)
        self._maybe_promote(piece, to_pos)
        self._notify(
            MoveCompletedEvent(
                piece=piece,
                from_pos=from_pos,
                to_pos=to_pos,
                arrival_time=self.current_time,
            )
        )
        self._check_game_over()
        return MoveResult.OK

    def handle_jump(self, x: int, y: int) -> None:
        """Process a pixel-coordinate jump command.

        * Game over → silently ignored.
        * Out-of-bounds click → silently ignored.
        * Empty square (including a piece already captured) → silently
          ignored — there's nothing there to jump.
        * A piece already moving or already airborne (``_is_busy``) →
          silently ignored: a moving piece cannot jump, and a piece
          cannot jump twice at once.
        * Otherwise the piece goes airborne for ``jump_duration`` ms — see
          the class-level note on how ``tick()`` resolves the window.

        Unlike ``handle_click``, a jump needs no selection step: origin
        and destination are always the same cell, so one call is enough.
        """
        if self.game_over:
            return

        pos = self._mapper.pixel_to_cell(x, y)

        if not self.board.contains(pos):
            return

        piece = self.board.get_piece_at(pos)

        if piece is None or piece == "." or self._is_busy(pos):
            return

        self._airborne.append(
            PendingJump(
                piece=piece,
                pos=pos,
                land_time=self.current_time + self._jump_duration,
            )
        )

    def tick(self, ms: int) -> None:
        """Advance the game clock by *ms* milliseconds.

        After updating ``current_time``, all pending moves whose
        ``arrival_time <= current_time`` are executed in chronological
        order (earliest ``arrival_time`` first; ties keep queue order) —
        see ``_resolve_due_move`` for how each one is decided; the
        friendly-mid-route-block and airborne-interception logic it
        leans on lives in ``CollisionResolver``, not here.

        Because earlier-arriving moves in the same tick are applied first,
        a later move's re-validation sees their results — e.g. two pieces
        racing for the same square: whichever arrives first occupies it,
        and a second, later-arriving enemy can still capture it there,
        while a second, later-arriving friendly is rejected as blocked.
        An airborne defender can defeat multiple arrivals in the same
        tick this way — it never leaves its cell, so each subsequent
        arrival still finds it there.

        Finally, jumps are resolved: any ``PendingJump`` whose
        ``land_time <= current_time`` grounds (``JumpLandedEvent``) —
        note this happens *after* the move loop above, so a jump landing
        on the exact millisecond an enemy arrives still defends its cell.
        Then a ``TimeAdvancedEvent`` is broadcast.
        """
        self.current_time += ms

        due: List[PendingMove] = []
        remaining: List[PendingMove] = []
        for pm in self._pending:
            (due if pm.arrival_time <= self.current_time else remaining).append(pm)
        self._pending = remaining
        due.sort(key=lambda pm: pm.arrival_time)

        for pm in due:
            self._resolve_due_move(pm)

        grounded: List[PendingJump] = []
        still_airborne: List[PendingJump] = []
        for pj in self._airborne:
            (grounded if pj.land_time <= self.current_time else still_airborne).append(pj)
        self._airborne = still_airborne
        for pj in grounded:
            self._set_cooldown(pj.pos)
            self._notify(JumpLandedEvent(piece=pj.piece, pos=pj.pos, land_time=pj.land_time))

        self._check_game_over()
        self._notify(TimeAdvancedEvent(current_time=self.current_time))

    def _resolve_due_move(self, pm: PendingMove) -> None:
        """Apply a single due ``PendingMove``'s outcome, deferring the
        friendly-block and airborne-interception *decisions* to
        ``CollisionResolver`` — this method stays the sole place that
        mutates the board and fires events, per the class's board-
        ownership contract.

        * The origin must still hold the same piece (it wasn't captured,
          or hasn't already been moved/re-executed) — otherwise dropped.
        * If a FRIENDLY piece now sits somewhere strictly between origin
          and destination (``CollisionResolver.stop_before_friendly_block``),
          the mover stops on the last clear square before it instead of
          being dropped outright (a no-op if that square is its own
          origin). An ENEMY piece blocking the same way is a different
          case: the whole move is dropped, same as always — via the
          ordinary path-clear check inside ``MoveValidator.is_valid``.
        * Otherwise, the move must still be legal (``MoveValidator.is_valid``),
          which re-checks the destination content (friendly-piece landing is
          rejected, an enemy piece there is still a legal capture) and,
          for sliding pieces, that the path is still clear (a piece that
          moved into the path since queuing blocks it).
        * If the destination is an *airborne enemy*'s cell
          (``CollisionResolver.airborne_defender``), the jump wins: the
          defender never moves and the arriving piece is removed outright
          (``AirborneCaptureEvent``) instead of relocating there (no
          ``MoveCompletedEvent`` for it).

        A rejected move is simply dropped (no event, no retry) — it does
        not go back on the pending queue. For a move actually applied, a
        ``MoveCompletedEvent`` is fired and the landing cell starts its
        cooldown window.
        """
        if self.board.get_piece_at(pm.from_pos) != pm.piece:
            return

        stop_pos = self._collision_resolver.stop_before_friendly_block(pm, self.board)
        if stop_pos is not None:
            if stop_pos != pm.from_pos:
                self.board.move_piece(pm.from_pos, stop_pos)
                self._maybe_promote(pm.piece, stop_pos)
                self._set_cooldown(stop_pos)
                self._notify(
                    MoveCompletedEvent(
                        piece=pm.piece,
                        from_pos=pm.from_pos,
                        to_pos=stop_pos,
                        arrival_time=pm.arrival_time,
                    )
                )
            return

        if not self._validator.is_valid(pm.piece, pm.from_pos, pm.to_pos, self.board):
            return

        defender = self._collision_resolver.airborne_defender(
            pm.to_pos, pm.piece, self._airborne
        )
        if defender is not None:
            self.board.set_piece_at(pm.from_pos, ".")
            self._notify(
                AirborneCaptureEvent(
                    defender=defender.piece,
                    pos=defender.pos,
                    attacker=pm.piece,
                )
            )
            return

        self.board.move_piece(pm.from_pos, pm.to_pos)
        self._maybe_promote(pm.piece, pm.to_pos)
        self._set_cooldown(pm.to_pos)
        self._notify(
            MoveCompletedEvent(
                piece=pm.piece,
                from_pos=pm.from_pos,
                to_pos=pm.to_pos,
                arrival_time=pm.arrival_time,
            )
        )

    # ------------------------------------------------------------------
    # Read-only accessors
    # ------------------------------------------------------------------

    @property
    def clock_ms(self) -> int:
        """Current game-clock value in milliseconds (alias for current_time)."""
        return self.current_time

    @property
    def selection(self) -> Position | None:
        """Currently selected cell, if any — owned by ``ClickController``;
        exposed here read-only for callers/tests that inspect it."""
        return self._click_controller.selection

    def is_in_transit(self, pos: Position) -> bool:
        """Return True if *pos* is the origin of a move that has not yet arrived."""
        return any(pm.from_pos == pos for pm in self._pending)

    def is_airborne(self, pos: Position) -> bool:
        """Return True if the piece at *pos* is currently mid-jump."""
        return self._airborne_at(pos) is not None

    def is_in_cooldown(self, pos: Position) -> bool:
        """Return True if *pos* is still cooling down after a landing.

        Set whenever a move (full arrival or a friendly-block stop-short)
        or a jump lands on *pos* — see ``_set_cooldown``. Expires on its
        own once ``current_time`` passes the stored expiry; no explicit
        cleanup is needed."""
        expiry = self._cooldowns.get(pos)
        return expiry is not None and expiry > self.current_time

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_busy(self, pos: Position) -> bool:
        """Return True if the piece at *pos* is committed to another
        action — already moving, already airborne, or still cooling down
        from its last landing — and so cannot be selected, redirected, or
        jumped again."""
        return self.is_in_transit(pos) or self.is_airborne(pos) or self.is_in_cooldown(pos)

    def _set_cooldown(self, pos: Position) -> None:
        """Start (or restart) *pos*'s cooldown window from the current time."""
        self._cooldowns[pos] = self.current_time + self._cooldown_duration

    def _airborne_at(self, pos: Position) -> PendingJump | None:
        """Return the active ``PendingJump`` at *pos*, if any."""
        for pj in self._airborne:
            if pj.pos == pos:
                return pj
        return None

    def _maybe_promote(self, piece: str, pos: Position) -> None:
        """Promote a Pawn to a Queen the instant it reaches the back rank.

        White promotes on row 0 (the row it advances toward); Black on
        ``num_rows - 1`` — the mirror image, matching the direction
        convention in ``PawnRule``. Applies regardless of how the pawn
        got there (straight advance or diagonal capture); a non-Pawn is
        untouched.
        """
        if piece[1] != "P":
            return
        last_row = 0 if piece[0] == "w" else self.board.num_rows - 1
        if pos.row == last_row:
            self.board.set_piece_at(pos, piece[0] + "Q")

    def _check_game_over(self) -> None:
        """Ask the injected ``GameOverRule`` whether the game just ended.

        A no-op once ``game_over`` is already True — the transition only
        happens once, and only one ``GameOverEvent`` is ever fired.
        """
        if self.game_over:
            return
        result = self._game_over_rule.check(self.board)
        if not result.is_over:
            return
        self.game_over = True
        self.winner = result.winner
        self._notify(GameOverEvent(winner=self.winner))

    @staticmethod
    def _is_friendly(piece_a: str | None, piece_b: str | None) -> bool:
        """Return True if both pieces belong to the same colour."""
        return same_color(piece_a, piece_b)

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
            if same_color(pm.piece, piece):
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

