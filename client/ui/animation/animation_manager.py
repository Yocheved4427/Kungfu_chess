from __future__ import annotations

import pathlib
import sys
from typing import TYPE_CHECKING, Dict, Union

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_GRAPHICS_DIR = _REPO_ROOT / "ui" / "graphics"
# ui/graphics' own modules (asset_loader.py, piece_state_machine.py,
# piece_view.py, sprite_sequence.py, img.py) import each other as flat
# sibling modules (e.g. `from img import Img`), which only resolves if
# their own directory is on sys.path — same convention main_gui.py and
# login_view.py already use for exactly this reason (see either
# module's own top-of-file comment). Done here directly (not just
# relied on via some other module having already done it) so this
# module also works if imported/tested on its own.
if str(_GRAPHICS_DIR) not in sys.path:
    sys.path.insert(0, str(_GRAPHICS_DIR))

from asset_loader import AssetLoader  # noqa: E402
from piece_state_machine import PieceStateMachine  # noqa: E402
from piece_view import PieceView  # noqa: E402

if TYPE_CHECKING:
    from img import Img

# ---------------------------------------------------------------------------
# Kung Fu Chess – Client Animation Manager
# ---------------------------------------------------------------------------
# Loads sprites from assets/<pieces_set>/<piece_code>/states/<state>/ —
# using each state's own config.json (frames_per_sec, is_loop,
# next_state_when_finished) — and renders real-time per-piece animation
# frames for the online client's Active Game screen
# (client.ui.screens.online_game_screen).
#
# Reuses, rather than re-implements, ui/graphics' existing, already-
# tested sprite pipeline:
#   * AssetLoader   — sprite/config.json loading, one
#     {state_name: SpriteSequence} per piece code, cached per code.
#   * PieceStateMachine — one piece's current state + elapsed time,
#     auto-chaining a non-looping state to its own config's
#     next_state_when_finished (e.g. jump -> short_rest -> long_rest
#     -> idle) without the caller driving that chain by hand.
#   * PieceView     — keeps one PieceStateMachine alive across frames
#     per piece, so its animation timing survives between renders
#     instead of restarting at frame 0 every call (see that class's
#     own docstring).
# The exact same three classes already back GraphicsBoardRenderer for
# the local/two-player game (main_gui.py) — this class is the online
# client's own entry point into them, not a second, forked copy of
# sprite loading or state-machine logic.
#
# One real difference from GraphicsBoardRenderer's own usage: that
# renderer drives PieceView.sync() with a full engine.snapshot.
# PieceSnapshot (is_in_transit/is_airborne booleans, diffed frame to
# frame). The wire protocol this client talks to
# (server.network.server.NetworkServer's GameStateUpdateMessage)
# carries only a flat board array of piece tokens — no per-piece
# pending/airborne/cooldown detail at all (the same documented
# limitation the root network_client.py / ui.game_loop.py's existing
# --username network mode already has, and already accepts: every
# piece there renders as "idle" too, for the same reason). This class
# therefore exposes set_state() for an explicit, caller-decided state
# rather than sync()'s snapshot-diffing; all five states (idle, move,
# jump, short_rest, long_rest) load and chain correctly through it, but
# client.ui.screens.online_game_screen only ever asks for "idle" today
# — "move"/"jump"/"short_rest"/"long_rest" become reachable the moment
# the wire protocol grows enough per-piece detail to justify them,
# without any change needed here.
# ---------------------------------------------------------------------------


class AnimationManager:
    """Owns one ``PieceView`` per currently-animated piece, keyed by a
    caller-chosen ``piece_id`` — e.g. ``"row,col"`` for whatever cell a
    piece currently occupies, if the caller has no more stable identity
    to key by across snapshots (the wire protocol has none; see this
    module's own docstring).
    """

    def __init__(self, assets_root: Union[str, pathlib.Path]) -> None:
        self._loader = AssetLoader(assets_root)
        self._views: Dict[str, PieceView] = {}

    def get_frame(self, piece_id: str, piece_token: str) -> "Img":
        """The frame that should be showing right now for *piece_id*
        (a piece whose board token is *piece_token*, e.g. ``"wP"`` —
        the same ``"<colour><type>"`` shape every board row already
        uses; see ``_asset_code``) — creates its ``PieceView``
        (starting in "idle") on first use.
        """
        return self._view_for(piece_id, piece_token).get_current_frame()

    def set_state(self, piece_id: str, piece_token: str, state_name: str) -> None:
        """Force *piece_id* directly into *state_name* (``"idle"``,
        ``"move"``, ``"jump"``, ``"short_rest"``, or ``"long_rest"``) —
        creates its ``PieceView`` on first use. A repeated call with
        the state it is already in restarts that state's animation
        from frame 0 (``PieceStateMachine.transition_to`` always resets
        elapsed time) — callers should only call this when the state
        has actually just changed, not every frame (mirrors
        ``PieceView.sync``'s own "only on a flag's rising edge" rule).
        """
        self._view_for(piece_id, piece_token).transition_to(state_name)

    def forget(self, piece_id: str) -> None:
        """Drop *piece_id*'s view — call once it's no longer on the
        board (moved away under a cell-keyed identity change, or
        captured), so a stale view doesn't leak forever."""
        self._views.pop(piece_id, None)

    def _view_for(self, piece_id: str, piece_token: str) -> PieceView:
        view = self._views.get(piece_id)
        if view is None:
            states = self._loader.load(self._asset_code(piece_token))
            view = PieceView(PieceStateMachine(states))
            self._views[piece_id] = view
        return view

    @staticmethod
    def _asset_code(piece_token: str) -> str:
        """``"wP"`` -> ``"PW"``: board rows spell a piece
        ``"<colour><TYPE>"`` (lowercase colour, uppercase type — see
        shared.models.piece_type/core board tokens), but this
        codebase's assets/ directory names each piece's folder
        ``"<TYPE><COLOUR>"`` instead (e.g. ``assets/pieces1/PW/``,
        ``.../BB/`` — verified against the actual directory listing,
        not assumed). This is the one place that reordering happens.
        """
        return piece_token[1] + piece_token[0].upper()
