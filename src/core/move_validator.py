"""Move legality -- thin re-export.

The actual rule implementation lives in ``engine/rules.py`` (piece-shape
validation, ``MoveValidator``) and ``engine/rule_engine.py`` (the
board-aware legality facade, ``RuleEngine``/``MoveResult``) at the repo
root, which the multiplayer server also imports directly for the exact
same legality decisions. No rules are duplicated here.
"""

from __future__ import annotations

from engine.rule_engine import MoveResult, RuleEngine
from engine.rules import MoveValidator

__all__ = ["MoveValidator", "RuleEngine", "MoveResult"]
