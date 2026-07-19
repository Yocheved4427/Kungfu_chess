from __future__ import annotations

import argparse
import logging
import pathlib

from core.config import VALID_PIECE_CHARS
from engine.board import AbstractBoard, TextBoard
from engine.board_validator import BoardValidationError, BoardValidator
from engine.game import GameEngine
from engine.game_state import GameState
from input.board_mapper import BoardMapper
from input.board_parser import BoardParser

logger = logging.getLogger(__name__)

STANDARD_BOARD_ROWS = [
    "bR bN bB bQ bK bB bN bR",
    "bP bP bP bP bP bP bP bP",
    ". . . . . . . .",
    ". . . . . . . .",
    ". . . . . . . .",
    ". . . . . . . .",
    "wP wP wP wP wP wP wP wP",
    "wR wN wB wQ wK wB wN wR",
]


def _load_board(board_path: "pathlib.Path | None") -> AbstractBoard:
    """Return the board to start the game with.

    Parses and validates *board_path* via the same ``BoardParser`` /
    ``BoardValidator`` pair ``main.py`` uses for the CLI pipeline — no
    second parser. Falls back to ``STANDARD_BOARD_ROWS`` (with a logged
    warning) if *board_path* is ``None``, unreadable, or fails
    validation; never raises.
    """
    if board_path is None:
        return TextBoard(STANDARD_BOARD_ROWS)

    try:
        with open(board_path, "r") as f:
            lines = f.readlines()
        board = BoardParser().parse(lines)
        BoardValidator(valid_chars=VALID_PIECE_CHARS).validate(board.get_rows())
        return board
    except (OSError, BoardValidationError) as e:
        logger.warning(
            "Failed to load board from %s (%s) — falling back to the standard starting layout.",
            board_path,
            e,
        )
        return TextBoard(STANDARD_BOARD_ROWS)


def _new_game(args: argparse.Namespace, mapper: BoardMapper) -> "tuple[GameEngine, GameState]":
    """Build a fresh ``GameEngine`` + ``GameState`` pair from *args*' launch
    settings (the same ``--board`` source ``_load_board`` used at startup)
    and the already-resolved *mapper*.

    Used both for the very first game and every restart. A restart can't
    just build a new ``GameState`` and keep the existing ``GameEngine``:
    ``GameEngine``'s default ``GameOverRule`` (``KingCaptureRule``) is
    stateful and explicitly documented as scoped to a single game — see
    that class's own docstring: "don't share a ``KingCaptureRule`` across
    two ``GameEngine`` instances." Reusing one would carry over which
    colours it saw as "armed" (and already lost) from the previous game,
    so the new game could report itself over immediately. A fresh
    ``GameEngine`` (which primes a fresh ``KingCaptureRule`` from the
    fresh board at construction) avoids that entirely.
    """
    board = _load_board(args.board)
    engine = GameEngine(board, mapper=mapper)
    state = GameState(board=board)
    return engine, state
