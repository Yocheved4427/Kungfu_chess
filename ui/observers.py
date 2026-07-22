from __future__ import annotations

import logging
from typing import Dict, Type

from ui.events import (
    AirborneCaptureEvent,
    GameEvent,
    GameOverEvent,
    MoveCompletedEvent,
    Observer,
    RenderEvent,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kung Fu Chess – Concrete Observers
# ---------------------------------------------------------------------------
# Two Bus subscribers (see ui/bus.py) that exist purely as hooks for now:
# each just logs what it *would* do. No audio playback, no client-side
# animation triggering — this is preparation for a future WebSocket
# server, which will replace these logger.info() calls with an actual
# outbound message once real clients exist to receive one.
# ---------------------------------------------------------------------------


class SoundTriggerObserver(Observer):
    """Logs which sound would play for each sound-worthy event.

    Only a fixed, small set of event types map to a sound; every other
    event (``RenderEvent``, ``TimeAdvancedEvent``, ``JumpLandedEvent`` —
    a jump landing with no capture is silent) is ignored outright.
    """

    _SOUND_NAMES: Dict[Type[GameEvent], str] = {
        MoveCompletedEvent: "move",
        AirborneCaptureEvent: "capture",
        GameOverEvent: "game-over",
    }

    def on_event(self, event: GameEvent) -> None:
        sound_name = self._SOUND_NAMES.get(type(event))
        if sound_name is None:
            return
        logger.info("Sound trigger: would play %r sound (%s)", sound_name, type(event).__name__)


class GameLifecycleObserver(Observer):
    """Logs a game's coarse start/end lifecycle transitions.

    "Start" is inferred from the first ``RenderEvent`` this instance
    ever receives — there's no dedicated "game started" event yet (see
    this module's own header), and ``RenderEvent`` is the earliest
    per-game signal already on the Bus (``GameEngine.request_render``).
    This is a heuristic, not a guarantee: nothing fires a ``RenderEvent``
    on its own, so a run that never requests a render never logs a
    start. "End" is exactly ``GameOverEvent`` — unambiguous, fires
    exactly once per game (see ``GameOverRule``).

    Stateful per instance (tracks whether its first ``RenderEvent`` has
    already been seen) — a fresh instance is needed per game, the same
    "rebuild everything per-game" convention ``_new_game``'s own
    docstring documents for ``GameEngine`` itself.
    """

    def __init__(self) -> None:
        self._started = False

    def on_event(self, event: GameEvent) -> None:
        if isinstance(event, RenderEvent):
            if not self._started:
                self._started = True
                logger.info("Game lifecycle: game started")
        elif isinstance(event, GameOverEvent):
            logger.info("Game lifecycle: game over (winner=%s)", event.winner)
