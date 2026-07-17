from __future__ import annotations

from typing import TYPE_CHECKING

from piece_state_machine import PieceStateMachine

if TYPE_CHECKING:
    from engine.snapshot import PieceSnapshot
    from img import Img

# ---------------------------------------------------------------------------
# Kung Fu Chess – Per-piece animation view
# ---------------------------------------------------------------------------
# One PieceView per piece currently on the board, kept alive across
# GraphicsBoardRenderer.render() calls (see GraphicsBoardRenderer's
# _piece_views) so a PieceStateMachine's animation timing survives
# between frames instead of restarting from frame 0 every render.
#
# sync() is the only thing that changes a view's state, and it only ever
# reacts to a flag that just flipped between the previous PieceSnapshot
# and the new one — not to "is currently true", which would re-trigger
# transition_to() (and reset the animation) every single frame a piece
# stays, say, mid-jump. That's the whole reason GraphicsBoardRenderer
# diffs snapshots rather than deriving a state fresh each frame.
# ---------------------------------------------------------------------------


class PieceView:
    """Kept-alive animation view for one piece: a ``PieceStateMachine``
    plus the last ``PieceSnapshot`` it was synced against."""

    def __init__(self, machine: PieceStateMachine):
        self._machine = machine
        self.snapshot: "PieceSnapshot | None" = None

    def get_current_frame(self) -> "Img":
        return self._machine.get_current_frame()

    def sync(self, snapshot: "PieceSnapshot") -> None:
        """Advance this piece's animation state for a new frame.

        Diffs *snapshot* against the last one this view saw (``None`` on
        a freshly-created view — i.e. this piece just appeared) and
        triggers at most one entry transition per status flag that just
        turned True:

        * ``is_in_transit`` False -> True enters "move". "move" loops
          (every piece's ``assets/pieces3/*/states/move/config.json``
          sets ``is_loop: true``), so it never auto-advances to its own
          configured ``next_state_when_finished`` on its own — this is
          what actually reads that field and exits "move" once transit
          ends, rather than hard-coding where a piece rests afterward.
        * ``is_airborne`` False -> True enters "jump". Unlike "move",
          "jump" is non-looping and its own ``next_state_when_finished``
          chain (jump -> short_rest -> long_rest -> idle, per this asset
          set's configs) auto-advances on its own via
          ``PieceStateMachine``, so nothing further is driven from here.

        ``is_in_cooldown`` is deliberately not wired to a transition:
        the asset configs define two distinct rest states (short_rest,
        long_rest), but GameSnapshot only exposes one boolean, so there
        is no non-guessed way to pick between them from here.
        """
        previous = self.snapshot
        self.snapshot = snapshot

        if previous is None:
            if snapshot.is_in_transit:
                self._machine.transition_to("move")
            elif snapshot.is_airborne:
                self._machine.transition_to("jump")
            return

        if not previous.is_in_transit and snapshot.is_in_transit:
            self._machine.transition_to("move")
        elif previous.is_in_transit and not snapshot.is_in_transit:
            move_sequence = self._machine.states["move"]
            self._machine.transition_to(move_sequence.next_state_when_finished)

        if not previous.is_airborne and snapshot.is_airborne:
            self._machine.transition_to("jump")
