from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from core.models import Color, PendingJump, PendingMove, Position
from engine.board import AbstractBoard
from engine.game_state import GameState

# ---------------------------------------------------------------------------
# Kung Fu Chess – Read-only snapshots
# ---------------------------------------------------------------------------
# A frozen, point-in-time copy of a live GameState, built on demand for
# consumers (currently GraphicsBoardRenderer) that should only ever look
# at the game, never mutate it. GameEngine remains the sole owner and
# mutator of GameState; nothing here changes that — from_state()/
# from_board()/from_piece() only ever READ their live-engine argument,
# the same "read-only, no mutation" contract engine.rules/engine.rule_engine
# already hold with AbstractBoard.
#
# Lives in engine/, not core/, because it depends on AbstractBoard and
# GameState — both engine-layer types. core.models is deliberately kept
# free of any engine import (see engine.game_state's module docstring),
# so a type that reads a GameState can't live there without inverting
# that dependency direction.
#
# Each class is frozen (immutable) and copies rather than aliases every
# mutable collection it touches (board cells into a nested tuple,
# ``pending``/``airborne`` lists into tuples), so a snapshot's values
# stay exactly what they were at the moment it was taken, no matter what
# happens to the live GameState afterward.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PieceSnapshot:
    """Immutable, read-only view of one occupied board cell.

    ``color``          – the piece's ``Color``, decoded from the token's
                          leading character (e.g. ``"w"`` -> ``Color.WHITE``).
    ``kind``            – the piece-type character (e.g. ``"K"``, ``"P"``),
                          the same "piece-type char" RuleEngine dispatches
                          on — see engine.rule_engine's module docstring.
    ``position``        – the cell this piece occupies.
    ``is_in_transit``   – mirrors ``GameEngine.is_in_transit``: True iff a
                          queued move has this cell as its origin.
    ``is_airborne``     – mirrors ``GameEngine.is_airborne``: True iff this
                          cell's piece is currently mid-jump.
    ``is_in_cooldown``  – mirrors ``GameEngine.is_in_cooldown``: True iff
                          this cell is still cooling down after a landing.
    """

    color: Color
    kind: str
    position: Position
    is_in_transit: bool = False
    is_airborne: bool = False
    is_in_cooldown: bool = False

    @classmethod
    def from_piece(
        cls,
        piece: str,
        position: Position,
        *,
        is_in_transit: bool = False,
        is_airborne: bool = False,
        is_in_cooldown: bool = False,
    ) -> "PieceSnapshot":
        """Build from a board token (e.g. ``"wK"``) and the cell it occupies.

        The token alone carries no status — a bare occupancy grid (see
        ``BoardSnapshot.from_board`` called without a ``state``) has no
        pending/airborne/cooldown data to report, so those default to
        False; ``BoardSnapshot.from_board(board, state)`` passes the real
        values in.
        """
        color = Color.WHITE if piece[0] == Color.WHITE.value else Color.BLACK
        kind = piece[1]
        return cls(
            color=color,
            kind=kind,
            position=position,
            is_in_transit=is_in_transit,
            is_airborne=is_airborne,
            is_in_cooldown=is_in_cooldown,
        )


@dataclass(frozen=True)
class BoardSnapshot:
    """Immutable grid of ``PieceSnapshot | None``, indexed ``[row][col]``.

    ``num_rows``/``num_cols`` name-match ``AbstractBoard``'s own
    properties rather than the task's "width/height" wording, since
    every existing caller in this codebase (``BoardMapper``,
    ``GraphicsBoardRenderer``, ``AbstractBoard`` itself) already uses
    ``num_rows``/``num_cols`` — see this module's own header for why
    consistency won out here.
    """

    num_rows: int
    num_cols: int
    cells: Tuple[Tuple[PieceSnapshot | None, ...], ...]

    @classmethod
    def from_board(cls, board: AbstractBoard, state: GameState | None = None) -> "BoardSnapshot":
        """Build from a live ``AbstractBoard``.

        Pass *state* to also populate each piece's transit/airborne/
        cooldown status (see ``PieceSnapshot``) — omit it for a plain
        occupancy-only snapshot, e.g. when no ``GameState`` is at hand.
        """
        rows = []
        for row in range(board.num_rows):
            row_cells = []
            for col in range(board.num_cols):
                pos = Position(row=row, col=col)
                token = board.get_piece_at(pos)
                if token is None or token == ".":
                    row_cells.append(None)
                elif state is None:
                    row_cells.append(PieceSnapshot.from_piece(token, pos))
                else:
                    expiry = state.cooldowns.get(pos)
                    row_cells.append(
                        PieceSnapshot.from_piece(
                            token,
                            pos,
                            is_in_transit=any(pm.from_pos == pos for pm in state.pending),
                            is_airborne=any(pj.pos == pos for pj in state.airborne),
                            is_in_cooldown=expiry is not None and expiry > state.current_time,
                        )
                    )
            rows.append(tuple(row_cells))
        return cls(num_rows=board.num_rows, num_cols=board.num_cols, cells=tuple(rows))

    def get_piece_at(self, position: Position) -> PieceSnapshot | None:
        """Return the snapshot at *position*, or ``None`` if empty/out of bounds.

        Mirrors ``AbstractBoard.get_piece_at`` so callers (e.g.
        ``GraphicsBoardRenderer``) need no code-shape change beyond
        swapping a live board for this snapshot.
        """
        if not (0 <= position.row < self.num_rows and 0 <= position.col < self.num_cols):
            return None
        return self.cells[position.row][position.col]


@dataclass(frozen=True)
class GameSnapshot:
    """Immutable, point-in-time view of a ``GameState``.

    ``board``         – occupancy + per-piece status at the moment of
                        the snapshot (see ``BoardSnapshot``).
    ``current_time``  – the game clock (ms) at the moment of the snapshot.
    ``game_over``     – whether the game had ended at that moment.
    ``winner``        – the winning ``Color`` at that moment, or ``None``.
    ``pending``       – queued moves not yet arrived, as of the snapshot.
    ``airborne``      – pieces mid-jump, as of the snapshot.
    """

    board: BoardSnapshot
    current_time: int
    game_over: bool
    winner: Color | None
    pending: Tuple[PendingMove, ...]
    airborne: Tuple[PendingJump, ...]

    @classmethod
    def from_state(cls, state: GameState) -> "GameSnapshot":
        """Build a full snapshot from a live ``GameState``.

        Only ever reads *state* — GameEngine remains the sole component
        that mutates it, exactly as before this snapshot layer existed.
        """
        return cls(
            board=BoardSnapshot.from_board(state.board, state),
            current_time=state.current_time,
            game_over=state.game_over,
            winner=state.winner,
            pending=tuple(state.pending),
            airborne=tuple(state.airborne),
        )
