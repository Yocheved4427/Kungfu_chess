from __future__ import annotations

from typing import Any, Dict

from shared.models.board import TextBoard
from shared.models.cell import Cell
from shared.models.color import Color
from core.models import MoveCheckpoint, PendingJump, PendingMove
from engine.game_state import GameState

from services.game_server.domain import PlayerMeta

# ---------------------------------------------------------------------------
# Kung Fu Chess -- Presentation layer for Pause & Resume
# (services/game_server/serialization.py)
# ---------------------------------------------------------------------------
# Pure functions only: dataclass <-> plain dict, no I/O, no Redis, no
# knowledge that the result is ever going to end up in Redis at all.
# Cell/PendingMove/PendingJump/MoveCheckpoint are plain frozen dataclasses
# with no built-in JSON support, so each gets an explicit to-dict/from-dict
# pair rather than a generic/reflective serializer -- same "explicit over
# clever" preference the rest of this codebase already follows (see
# GameEvent.to_dict()).
# ---------------------------------------------------------------------------


def cell_to_dict(cell: Cell) -> dict:
    return {"row": cell.row, "col": cell.col}


def cell_from_dict(d: dict) -> Cell:
    return Cell(d["row"], d["col"])


def checkpoint_to_dict(cp: MoveCheckpoint) -> dict:
    return {"pos": cell_to_dict(cp.pos), "due_time": cp.due_time}


def checkpoint_from_dict(d: dict) -> MoveCheckpoint:
    return MoveCheckpoint(pos=cell_from_dict(d["pos"]), due_time=d["due_time"])


def pending_move_to_dict(pm: PendingMove) -> dict:
    return {
        "piece": pm.piece,
        "from_pos": cell_to_dict(pm.from_pos),
        "to_pos": cell_to_dict(pm.to_pos),
        "arrival_time": pm.arrival_time,
        "start_time": pm.start_time,
        "checkpoints": [checkpoint_to_dict(cp) for cp in pm.checkpoints],
        "next_checkpoint": pm.next_checkpoint,
    }


def pending_move_from_dict(d: dict) -> PendingMove:
    return PendingMove(
        piece=d["piece"],
        from_pos=cell_from_dict(d["from_pos"]),
        to_pos=cell_from_dict(d["to_pos"]),
        arrival_time=d["arrival_time"],
        start_time=d["start_time"],
        checkpoints=tuple(checkpoint_from_dict(cp) for cp in d["checkpoints"]),
        next_checkpoint=d["next_checkpoint"],
    )


def pending_jump_to_dict(pj: PendingJump) -> dict:
    return {"piece": pj.piece, "pos": cell_to_dict(pj.pos), "land_time": pj.land_time}


def pending_jump_from_dict(d: dict) -> PendingJump:
    return PendingJump(piece=d["piece"], pos=cell_from_dict(d["pos"]), land_time=d["land_time"])


def player_meta_to_dict(meta: PlayerMeta) -> dict:
    return {"user_id": meta.user_id, "elo": meta.elo, "color": meta.color.value}


def player_meta_from_dict(d: dict) -> PlayerMeta:
    return PlayerMeta(user_id=d["user_id"], elo=d["elo"], color=Color(d["color"]))


def game_state_to_dict(board: TextBoard, state: GameState) -> dict:
    """requirement 1: board matrix, piece cooldowns, timer states (+
    in-flight moves/jumps -- omitting those would silently drop a move
    that was mid-flight the instant the game was paused, since it would
    then never arrive on resume)."""
    return {
        "board_rows": board.get_rows(),
        "current_time": state.current_time,
        "pending": [pending_move_to_dict(pm) for pm in state.pending],
        "airborne": [pending_jump_to_dict(pj) for pj in state.airborne],
        "cooldowns": [
            {"row": cell.row, "col": cell.col, "expiry": expiry}
            for cell, expiry in state.cooldowns.items()
        ],
        "game_over": state.game_over,
        "winner": state.winner.value if state.winner is not None else None,
    }


def game_state_from_dict(payload: Dict[str, Any]) -> tuple[TextBoard, GameState]:
    board = TextBoard(payload["board_rows"])
    state = GameState(
        board=board,
        current_time=payload["current_time"],
        pending=[pending_move_from_dict(d) for d in payload["pending"]],
        airborne=[pending_jump_from_dict(d) for d in payload["airborne"]],
        cooldowns={cell_from_dict(c): c["expiry"] for c in payload["cooldowns"]},
        game_over=payload["game_over"],
        winner=Color(payload["winner"]) if payload["winner"] is not None else None,
    )
    return board, state
