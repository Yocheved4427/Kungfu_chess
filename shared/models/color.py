from __future__ import annotations

from enum import Enum

# ---------------------------------------------------------------------------
# Kung Fu Chess – Piece Colour
# ---------------------------------------------------------------------------
# Moved here from core.models (Iteration: shared/ extraction) — the same
# Color class, same values, same import path for anything that already
# does ``Color.WHITE``/``Color.BLACK`` after updating its own import
# statement. This is the ONE Color used everywhere in this project
# (engine, server, ui, tests) — nothing else defines a second, separate
# Color type.
# ---------------------------------------------------------------------------


class Color(Enum):
    """Piece colour encoded as the leading character of a board token."""
    WHITE = "w"
    BLACK = "b"
