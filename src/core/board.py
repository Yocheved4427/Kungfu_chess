"""Board grid & cell-address types -- thin re-export.

The actual implementation lives in ``shared/models/board.py`` and
``shared/models/cell.py`` (repo root), which the multiplayer server
(``server/``) also imports directly. This module exists purely so local
game code can write ``from src.core.board import TextBoard, Cell``
instead of reaching across into ``shared.models`` itself -- it adds no
behaviour of its own.
"""

from __future__ import annotations

from shared.models.board import AbstractBoard, TextBoard
from shared.models.cell import Cell

__all__ = ["AbstractBoard", "TextBoard", "Cell"]
