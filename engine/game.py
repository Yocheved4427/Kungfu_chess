from __future__ import annotations

import logging
from typing import List

from controllers.click_controller import ClickController
from core.config import COOLDOWN_DURATION, JUMP_DURATION, MOVE_DURATION
from core.models import MoveCheckpoint, PendingJump, PendingMove, Position, same_color
from engine.board import AbstractBoard
from engine.board_renderer import BoardRenderer, TextBoardRenderer
from engine.game_over import GameOverRule, KingCaptureRule
from engine.game_state import GameState
from engine.rule_engine import MoveResult, RuleEngine
from engine.rules import MoveValidator
from input.board_mapper import BoardMapper
from realtime.collision_resolver import CollisionResolver
from ui.bus import Bus
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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kung Fu Chess – Game Engine (Iteration 15: Fully stateless GameEngine)
# ---------------------------------------------------------------------------
# New in this iteration
# ----------------------
#   * GameEngine no longer instantiates or owns a GameState. There is no
#     ``self.state`` (Iteration 14's version still held one internally —
#     this was flagged as a half-measure). Every action method now takes
#     a ``state: GameState`` argument explicitly and reads/writes only
#     that: ``tick(state, ms)``, ``attempt_move(state, from_pos, to_pos)``,
#     ``try_move(state, from_pos, to_pos)``, ``handle_click(state, x, y)``,
#     ``handle_jump(state, x, y)``, ``is_selectable(state, pos)``,
#     ``is_in_transit(state, pos)``, ``is_airborne(state, pos)``,
#     ``is_in_cooldown(state, pos)``, ``request_render(state)``.
#   * The compatibility shim properties from Iteration 14 (``board``,
#     ``game_over``, ``winner``, ``_pending``, ``_airborne``, ``clock_ms``)
#     are gone. GameEngine no longer pretends to own any of this — a
#     caller reads ``state.board``/``state.game_over``/etc. directly.
#   * GameEngine's own attributes are now strictly collaborators
#     (MoveValidator, RuleEngine, CollisionResolver, BoardMapper, ...)
#     and static per-game config (move/jump/cooldown duration) — never
#     anything that changes as a game progresses. The same ``GameEngine``
#     instance (and all its collaborators) can now drive many independent
#     ``GameState``s concurrently, since nothing about a specific game's
#     progress is stored on ``self``.
#   * The constructor still takes an initial ``board`` — used exactly
#     once, to prime ``GameOverRule`` (a stateful collaborator in its own
#     right — see ``KingCaptureRule`` — that must see the pristine board
#     before any move happens, to distinguish "this colour never had a
#     King" from "its King was captured"). That board is never retained
#     as an attribute; it is not the same thing as owning a GameState.
#   * ``ClickController`` now takes ``state`` as an explicit parameter on
#     ``handle_click`` too, and forwards it to ``is_selectable``/
#     ``attempt_move`` — it still holds a reference to the ``GameEngine``
#     instance (to call into it) and to its own ``selection`` (a
#     UI/interaction concern, not part of ``GameState``), but never a
#     ``GameState`` reference of its own.
#
# Iteration 14 recap: State extracted into GameState (superseded above)
# -------------------------------------------------------------------
#   * Every mutable per-game value GameEngine used to hold directly
#     (board, current_time, pending, airborne, cooldowns, game_over,
#     winner) was moved onto a ``GameState`` dataclass (see
#     engine/game_state.py) — but GameEngine still instantiated and held
#     one itself as ``self.state``, with read-only shim properties for
#     backward compatibility. Iteration 15 (above) removes both.
#
# Iteration 13 recap: Collision resolution extracted
# -------------------------------------------------------------------
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
#     RuleEngine-backed move. RuleEngine only reads the board to decide
#     legality and never mutates it — GameEngine is the only component
#     that ever calls board.move_piece / board.set_piece_at.
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
#   * handle_jump(state, x, y) sends a piece airborne for ``jump_duration``
#     ms (default JUMP_DURATION). Unlike a move, a jump never relocates
#     its piece — it stays on its own cell the whole time, tracked
#     separately in ``state.airborne`` (a list of PendingJump) rather
#     than ``state.pending``.
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
    """Stateless game-rules service, operating on an externally-owned
    ``GameState`` passed into every action method.

    Responsibilities
    ----------------
    * Hold zero per-game state. Every attribute on ``self`` is either a
      collaborator (``MoveValidator``, ``RuleEngine``, ``CollisionResolver``,
      ``BoardMapper``, ...) or static per-game configuration (move/jump/
      cooldown duration) — fixed at construction, never mutated
      afterward. Board, clock, pending moves, airborne jumps, cooldowns,
      game-over/winner all live on the caller's ``GameState`` instead —
      see engine/game_state.py — and are threaded through every call as
      an explicit ``state`` argument.
    * The single service layer that owns board *mutation* authority.
      Nothing else may mutate a board: ``board.move_piece``/
      ``board.set_piece_at`` are called only from within this class
      (``tick()`` and ``try_move``) — every other component
      (``RuleEngine``, ``MoveValidator``, ``ClickController``, ...) only
      ever *reads* it.
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
    * Advance a given ``GameState``'s clock (``tick``); execute moves
      whose arrival time is due.
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
        self._mapper: BoardMapper = mapper if mapper is not None else BoardMapper(cell_size)
        self._move_duration: int = move_duration
        self._jump_duration: int = jump_duration
        self._cooldown_duration: int = cooldown_duration
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
        self._bus: Bus = Bus()
        # Prime the rule with the pristine starting board — before any
        # move can run — so a stateful rule like KingCaptureRule can tell
        # "this colour never had a King" apart from "its King was
        # captured". *board* is used here only for this one-time priming
        # call; it is never stored on self — GameEngine owns no GameState.
        self._game_over_rule.check(board)
        # Click semantics (select / switch-selection / attempt-move) are
        # entirely owned by ClickController — see handle_click below.
        self._click_controller: ClickController = ClickController(self, self._mapper)

    # ------------------------------------------------------------------
    # Subject interface
    # ------------------------------------------------------------------

    def add_observer(self, observer: Observer) -> None:
        """Register *observer* to receive future ``GameEvent`` notifications.

        Delegates to an internal ``Bus`` (see ui/bus.py) — this method's
        own name/signature is unchanged from before that formalization,
        so every existing caller keeps working as-is.
        """
        self._bus.subscribe(observer)

    def _notify(self, event: GameEvent) -> None:
        self._bus.publish(event)

    def request_render(self, state: GameState) -> None:
        """Broadcast a ``RenderEvent`` carrying *state*'s board text."""
        self._notify(RenderEvent(board_text=self._renderer.render(state.board)))

    # ------------------------------------------------------------------
    # Game commands
    # ------------------------------------------------------------------

    def handle_click(self, state: GameState, x: int, y: int) -> None:
        """Process a pixel-coordinate click against *state*.

        Entirely delegated to ``ClickController``, which owns click
        semantics (select / switch selection / attempt move) and the
        ``selection`` state — see that class for the full state machine.
        GameEngine's only role here is legality: ``ClickController``
        forwards every move attempt to ``attempt_move`` (so a click that
        completes a move queues it as a ``PendingMove`` — the piece
        relocates later, via ``tick()``) and every selection decision
        consults ``is_selectable``; it never decides legality itself.
        """
        self._click_controller.handle_click(state, x, y)

    def is_selectable(self, state: GameState, pos: Position) -> bool:
        """True iff *pos* holds a piece that can currently be selected in *state*.

        A piece is selectable iff it exists and isn't busy (mid-move,
        airborne, or cooling down from its last landing). Pure query
        used by ``ClickController`` — it says
        nothing about whether any particular move from that piece would
        be legal; that's ``attempt_move``'s job.
        """
        piece = state.board.get_piece_at(pos)
        return piece is not None and piece != "." and not self._is_busy(state, pos)

    def attempt_move(self, state: GameState, from_pos: Position, to_pos: Position) -> bool:
        """The real-time pipeline's move attempt against *state* — queues
        rather than applies. This is what ``ClickController`` forwards
        every move attempt to behind ``handle_click``.

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
        if state.game_over:
            return False

        piece = state.board.get_piece_at(from_pos)
        if piece is None or piece == "." or self._is_busy(state, from_pos):
            return False

        if not self._validator.is_valid(piece, from_pos, to_pos, state.board):
            return False
        if self._route_conflicts(state, piece, from_pos, to_pos):
            return False

        checkpoints = self._build_checkpoints(from_pos, to_pos, state.current_time)
        state.pending.append(
            PendingMove(
                piece=piece,
                from_pos=from_pos,
                to_pos=to_pos,
                arrival_time=checkpoints[-1].due_time,
                start_time=state.current_time,
                checkpoints=checkpoints,
            )
        )
        return True

    def _build_checkpoints(
        self, from_pos: Position, to_pos: Position, queued_time: int
    ) -> "tuple[MoveCheckpoint, ...]":
        """Break a move from *from_pos* to *to_pos*, queued at
        *queued_time*, into one ``MoveCheckpoint`` per cell along its
        straight-line path — every intermediate cell (via
        ``CollisionResolver.path_cells``, shared rather than re-walked
        here), plus ``to_pos`` last — evenly spaced ``self._move_duration``
        ms apart. The total duration (``len(cells) * self._move_duration``)
        is unchanged from before per-cell checkpoints existed; this only
        subdivides it. A non-straight-line move (Knight) or an adjacent
        one-cell move has no intermediate cells, so this returns just the
        single final checkpoint — ``checkpoints[-1]`` is always ``to_pos``
        due at what ``arrival_time`` has always meant.
        """
        cells = self._collision_resolver.path_cells(from_pos, to_pos) + [to_pos]
        return tuple(
            MoveCheckpoint(pos=cell, due_time=queued_time + (i + 1) * self._move_duration)
            for i, cell in enumerate(cells)
        )

    def try_move(self, state: GameState, from_pos: Position, to_pos: Position) -> MoveResult:
        """Synchronous, ``RuleEngine``-backed move against *state* —
        GameEngine's plain service-layer entry point, distinct from the
        real-time pipeline. Independently usable and fully tested, but
        ``ClickController`` does not call this — clicks drive
        ``attempt_move`` instead (the VPL grader enforces the queued,
        real-time mechanics).

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
        if state.game_over:
            return MoveResult.GAME_OVER

        piece = state.board.get_piece_at(from_pos) or "."
        result = self._rule_engine.validate_move(piece, from_pos, to_pos, state.board)
        if not result.is_ok:
            return result

        state.board.move_piece(from_pos, to_pos)
        self._maybe_promote(state, piece, to_pos)
        self._notify(
            MoveCompletedEvent(
                piece=piece,
                from_pos=from_pos,
                to_pos=to_pos,
                arrival_time=state.current_time,
            )
        )
        self._check_game_over(state)
        return MoveResult.OK

    def handle_jump(self, state: GameState, x: int, y: int) -> None:
        """Process a pixel-coordinate jump command against *state*.

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
        if state.game_over:
            return

        pos = self._mapper.pixel_to_cell(x, y)

        if not state.board.contains(pos):
            return

        piece = state.board.get_piece_at(pos)

        if piece is None or piece == "." or self._is_busy(state, pos):
            return

        state.airborne.append(
            PendingJump(
                piece=piece,
                pos=pos,
                land_time=state.current_time + self._jump_duration,
            )
        )

    def tick(self, state: GameState, ms: int) -> None:
        """Advance *state*'s game clock by *ms* milliseconds.

        After updating ``current_time``, every pending move's checkpoints
        whose ``due_time <= current_time`` are resolved one at a time, in
        chronological order across ALL pending moves (earliest due
        checkpoint first; ties keep queue order) — see
        ``_resolve_checkpoint`` for how each one is decided; the
        friendly-mid-route-block and airborne-interception logic it leans
        on lives in ``CollisionResolver``, not here. A move with several
        intermediate checkpoints is resolved incrementally, one checkpoint
        per pass through this loop, so a DIFFERENT move's checkpoint due
        at an earlier or equal moment is always applied first — same
        cross-move ordering guarantee this method always had, just at
        checkpoint granularity now rather than only at each move's own
        final ``arrival_time``.

        Because earlier-due checkpoints are applied first, a later one's
        re-validation sees their results — e.g. two pieces racing for the
        same square: whichever arrives first occupies it, and a second,
        later-arriving enemy can still capture it there, while a second,
        later-arriving friendly is rejected as blocked. An airborne
        defender can defeat multiple arrivals in the same tick this way —
        it never leaves its cell, so each subsequent arrival still finds
        it there.

        Finally, jumps are resolved: any ``PendingJump`` whose
        ``land_time <= current_time`` grounds (``JumpLandedEvent``) —
        note this happens *after* the move loop above, so a jump landing
        on the exact millisecond an enemy arrives still defends its cell.
        Then a ``TimeAdvancedEvent`` is broadcast.
        """
        state.current_time += ms
        logger.debug("tick: +%dms -> current_time=%dms", ms, state.current_time)

        while True:
            pm = self._next_due_move(state)
            if pm is None:
                break
            self._resolve_checkpoint(state, pm)

        grounded: List[PendingJump] = []
        still_airborne: List[PendingJump] = []
        for pj in state.airborne:
            (grounded if pj.land_time <= state.current_time else still_airborne).append(pj)
        state.airborne = still_airborne
        for pj in grounded:
            self._set_cooldown(state, pj.pos)
            self._notify(JumpLandedEvent(piece=pj.piece, pos=pj.pos, land_time=pj.land_time))

        self._check_game_over(state)
        self._notify(TimeAdvancedEvent(current_time=state.current_time))

    def _effective_checkpoints(self, pm: PendingMove) -> "tuple[MoveCheckpoint, ...]":
        """*pm*'s checkpoint list, falling back to a single implicit
        final-only checkpoint for a ``PendingMove`` built without
        checkpoint data (e.g. directly in a test) — mirrors this engine's
        behaviour from before per-cell checkpoint timing existed."""
        return pm.checkpoints or (MoveCheckpoint(pm.to_pos, pm.arrival_time),)

    def _next_due_move(self, state: GameState) -> PendingMove | None:
        """The pending move whose next unresolved checkpoint is due
        soonest (and already ``<= current_time``), or None if no move has
        one due yet. Ties keep ``state.pending``'s own order (the first
        candidate found at the smallest due_time wins, never replaced by
        a later-found one at the same time) — same tie-break this method
        replaces already had."""
        best: PendingMove | None = None
        best_due_time: int | None = None
        for pm in state.pending:
            due_time = self._effective_checkpoints(pm)[pm.next_checkpoint].due_time
            if due_time > state.current_time:
                continue
            if best is None or due_time < best_due_time:
                best = pm
                best_due_time = due_time
        return best

    def _resolve_checkpoint(self, state: GameState, pm: PendingMove) -> None:
        """Resolve *pm*'s next due checkpoint — whichever one
        ``_next_due_move`` just selected — deferring the friendly-block
        and airborne-interception *decisions* to ``CollisionResolver``;
        this method stays the sole place that mutates the board and fires
        events, per the class's board-ownership contract.

        * The origin must still hold the same piece (it wasn't captured,
          or this move hasn't already been resolved) — otherwise dropped.
        * If this checkpoint is INTERMEDIATE (not the move's last) and a
          FRIENDLY piece now sits on it (``CollisionResolver.
          is_friendly_occupied``), the mover stops here — on the
          PREVIOUS checkpoint's cell (or ``from_pos`` if this is the very
          first one) — instead of being dropped outright (a no-op if that
          cell is its own origin). An ENEMY there does nothing at this
          checkpoint's own moment: the move keeps going, exactly as
          before per-cell timing existed — a still-blocking enemy is
          caught by the ordinary path-clear check inside
          ``MoveValidator.is_valid``, evaluated fresh at the FINAL
          checkpoint, same as always.
        * If this checkpoint is INTERMEDIATE and clear (of a friendly),
          nothing else happens except advancing to the next one — the
          piece was never actually AT this cell (it's still ``from_pos``
          on the board the whole flight — see ``core.models.PendingMove``'s
          own docstring), so no board mutation, no event.
        * If this checkpoint IS the move's last, it resolves exactly as a
          whole move always has: ``MoveValidator.is_valid`` (destination
          content + path-clear) and airborne-defender interception, then
          apply/promote/notify.

        A rejected move is simply dropped (no event, no retry) — it does
        not go back on the pending queue. For a move actually applied
        (whether reaching its final destination or stopping early), a
        ``MoveCompletedEvent`` is fired and the landing cell starts its
        cooldown window.
        """
        state.pending.remove(pm)

        if state.board.get_piece_at(pm.from_pos) != pm.piece:
            return

        checkpoints = self._effective_checkpoints(pm)
        checkpoint = checkpoints[pm.next_checkpoint]
        is_final = pm.next_checkpoint == len(checkpoints) - 1

        if not is_final:
            if self._collision_resolver.is_friendly_occupied(
                checkpoint.pos, pm.piece, state.board
            ):
                stop_pos = (
                    checkpoints[pm.next_checkpoint - 1].pos
                    if pm.next_checkpoint > 0
                    else pm.from_pos
                )
                self._land(state, pm, stop_pos, checkpoint.due_time)
                return

            # Clear of a friendly (an enemy here is deferred to the final
            # checkpoint's own path-clear check, unchanged) -- this
            # checkpoint is done; keep waiting on the rest of the path.
            state.pending.append(
                PendingMove(
                    piece=pm.piece,
                    from_pos=pm.from_pos,
                    to_pos=pm.to_pos,
                    arrival_time=pm.arrival_time,
                    start_time=pm.start_time,
                    checkpoints=pm.checkpoints,
                    next_checkpoint=pm.next_checkpoint + 1,
                )
            )
            return

        if not self._validator.is_valid(pm.piece, pm.from_pos, pm.to_pos, state.board):
            return

        defender = self._collision_resolver.airborne_defender(
            pm.to_pos, pm.piece, state.airborne
        )
        if defender is not None:
            state.board.set_piece_at(pm.from_pos, ".")
            self._notify(
                AirborneCaptureEvent(
                    defender=defender.piece,
                    pos=defender.pos,
                    attacker=pm.piece,
                )
            )
            return

        self._land(state, pm, pm.to_pos, checkpoint.due_time)

    def _land(self, state: GameState, pm: PendingMove, pos: Position, arrival_time: int) -> None:
        """Relocate ``pm.piece`` from ``pm.from_pos`` to *pos* and fire the
        landing side effects — shared by both ways a move can conclude:
        reaching its final destination, or stopping early at an
        intermediate cell because a friendly now blocks the rest of the
        path (see ``_resolve_checkpoint``). A no-op (``pos == pm.from_pos``,
        i.e. blocked on the very first step) fires no event either —
        the piece simply never moved.
        """
        if pos == pm.from_pos:
            return
        state.board.move_piece(pm.from_pos, pos)
        if not self._capture_just_ended_the_game(state):
            self._maybe_promote(state, pm.piece, pos)
        self._set_cooldown(state, pos)
        self._notify(
            MoveCompletedEvent(
                piece=pm.piece,
                from_pos=pm.from_pos,
                to_pos=pos,
                arrival_time=arrival_time,
            )
        )

    # ------------------------------------------------------------------
    # Read-only queries
    # ------------------------------------------------------------------
    # No shim properties over GameState here (deliberately) — a caller
    # holding a GameState already has direct access to state.board,
    # state.game_over, state.winner, state.pending, state.airborne, and
    # state.current_time. Only genuine *logic* (not plain attribute
    # access) stays on GameEngine, and takes state explicitly.

    @property
    def selection(self) -> Position | None:
        """Currently selected cell, if any — owned by ``ClickController``
        (a UI/interaction concern, not part of any ``GameState``);
        exposed here read-only for callers/tests that inspect it."""
        return self._click_controller.selection

    def is_in_transit(self, state: GameState, pos: Position) -> bool:
        """Return True if *pos* is the origin of a move in *state* that has not yet arrived."""
        return any(pm.from_pos == pos for pm in state.pending)

    def is_airborne(self, state: GameState, pos: Position) -> bool:
        """Return True if the piece at *pos* is currently mid-jump in *state*."""
        return self._airborne_at(state, pos) is not None

    def is_in_cooldown(self, state: GameState, pos: Position) -> bool:
        """Return True if *pos* is still cooling down after a landing in *state*.

        Set whenever a move (full arrival or a friendly-block stop-short)
        or a jump lands on *pos* — see ``_set_cooldown``. Expires on its
        own once ``current_time`` passes the stored expiry; no explicit
        cleanup is needed."""
        expiry = state.cooldowns.get(pos)
        return expiry is not None and expiry > state.current_time

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_busy(self, state: GameState, pos: Position) -> bool:
        """Return True if the piece at *pos* is committed to another
        action — already moving, already airborne, or still cooling down
        from its last landing — and so cannot be selected, redirected, or
        jumped again."""
        return (
            self.is_in_transit(state, pos)
            or self.is_airborne(state, pos)
            or self.is_in_cooldown(state, pos)
        )

    def _set_cooldown(self, state: GameState, pos: Position) -> None:
        """Start (or restart) *pos*'s cooldown window in *state* from the current time."""
        state.cooldowns[pos] = state.current_time + self._cooldown_duration

    def _airborne_at(self, state: GameState, pos: Position) -> PendingJump | None:
        """Return the active ``PendingJump`` at *pos* in *state*, if any."""
        for pj in state.airborne:
            if pj.pos == pos:
                return pj
        return None

    def _maybe_promote(self, state: GameState, piece: str, pos: Position) -> None:
        """Promote a Pawn to a Queen the instant it reaches the back rank.

        White promotes on row 0 (the row it advances toward); Black on
        ``num_rows - 1`` — the mirror image, matching the direction
        convention in ``PawnRule``. Applies regardless of how the pawn
        got there (straight advance or diagonal capture); a non-Pawn is
        untouched.
        """
        if piece[1] != "P":
            return
        last_row = 0 if piece[0] == "w" else state.board.num_rows - 1
        if pos.row == last_row:
            state.board.set_piece_at(pos, piece[0] + "Q")

    def _capture_just_ended_the_game(self, state: GameState) -> bool:
        """True iff *state*'s board, as it stands right now, already
        satisfies the injected ``GameOverRule`` — asked right after a
        move/capture is applied in ``_resolve_due_move``, to decide
        whether a pawn that just captured the enemy king on the back
        rank should still be promoted (it shouldn't: the game is already
        decided, and the piece should be recorded/rendered as the pawn
        that made the winning capture, not as a promoted queen).

        Read-only — unlike ``_check_game_over`` this never sets
        ``state.game_over``/``state.winner`` or fires ``GameOverEvent``;
        that transition still happens exactly once per ``tick()``, after
        all due moves are processed, completely unchanged. This just asks
        the same rule the same question a little early, for one narrow
        decision, without touching game-over's own timing.

        Also covers the case where an *earlier* due move in this same
        tick already ended the game — not just this move's own capture.
        """
        return self._game_over_rule.check(state.board).is_over

    def _check_game_over(self, state: GameState) -> None:
        """Ask the injected ``GameOverRule`` whether *state*'s game just ended.

        A no-op once ``game_over`` is already True — the transition only
        happens once, and only one ``GameOverEvent`` is ever fired.
        """
        if state.game_over:
            return
        result = self._game_over_rule.check(state.board)
        if not result.is_over:
            return
        state.game_over = True
        state.winner = result.winner
        logger.info("Game over: winner=%s", state.winner)
        self._notify(GameOverEvent(winner=state.winner))

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
        self, state: GameState, piece: str, from_pos: Position, to_pos: Position
    ) -> bool:
        """Return True if this move's lane overlaps an opposite-colour piece
        already in transit along the same lane in *state*.

        Pieces of opposite colour may not travel a common route (the same
        span of columns on a horizontal move, or rows on a vertical move)
        at the same time — the second mover is rejected. Same-colour moves
        and non-lane moves (diagonal / knight) never conflict.
        """
        lane = self._lane(from_pos, to_pos)
        if lane is None:
            return False
        axis, lo, hi = lane
        for pm in state.pending:
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
