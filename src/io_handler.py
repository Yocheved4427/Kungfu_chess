from __future__ import annotations

from typing import Callable, List, TextIO

from src.board import AbstractBoard
from src.board_parser import BoardParser
from src.board_validator import BoardValidator
from src.engine import GameEngine
from src.events import GameEvent, Observer, RenderEvent

# ---------------------------------------------------------------------------
# Kung Fu Chess – I/O handler (Iteration 3)
# ---------------------------------------------------------------------------
# Updated in Iteration 3:
#   * Now implements the ``Observer`` interface.
#   * Registers itself with the ``GameEngine`` on ``run()``.
#   * ``print board`` calls ``engine.request_render()`` instead of reading
#     ``engine.board.render()`` directly, keeping IO and render logic fully
#     decoupled.
# ---------------------------------------------------------------------------


class ChessIOHandler(Observer):
    """Reads a structured text stream, constructs a ``GameEngine``, and executes
    each command by delegating to the engine.

    Implements ``Observer`` to receive ``RenderEvent`` notifications from the
    engine and write rendered board text to the output stream.

    Input format::

        Board:
        wR wN wB wQ wK wB wN wR
        ...
        Commands:
        click 350 50
        wait 200
        print board
    """

    def __init__(
        self,
        reader: TextIO,
        writer: TextIO,
        parser: BoardParser,
        validator: BoardValidator,
        engine_factory: Callable[[AbstractBoard], GameEngine],
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._parser = parser
        self._validator = validator
        self._engine_factory = engine_factory

    # ------------------------------------------------------------------
    # Observer
    # ------------------------------------------------------------------

    def on_event(self, event: GameEvent) -> None:
        """Write board text to the output stream on ``RenderEvent``."""
        if isinstance(event, RenderEvent):
            self._writer.write(event.board_text + "\n")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Execute the full read → validate → command-dispatch pipeline."""
        board_lines, command_lines = self._split_sections(
            self._reader.readlines()
        )
        board = self._parser.parse(board_lines)
        self._validator.validate(board.get_rows())
        engine = self._engine_factory(board)
        engine.add_observer(self)
        self._execute_commands(engine, command_lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_sections(
        raw_lines: List[str],
    ) -> tuple[List[str], List[str]]:
        """Partition *raw_lines* into board lines and command lines."""
        board_lines: List[str] = []
        command_lines: List[str] = []
        in_board = False
        in_commands = False

        for line in raw_lines:
            clean = line.strip()
            if clean == "Board:":
                in_board = True
                in_commands = False
                continue
            if clean == "Commands:":
                in_board = False
                in_commands = True
                continue
            if in_board:
                board_lines.append(line.rstrip("\r\n"))
            elif in_commands:
                command_lines.append(clean)

        return board_lines, command_lines

    def _execute_commands(
        self, engine: GameEngine, command_lines: List[str]
    ) -> None:
        """Dispatch each command line to the appropriate engine method."""
        for line in command_lines:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "click" and len(parts) == 3:
                engine.handle_click(int(parts[1]), int(parts[2]))
            elif parts[0] == "wait" and len(parts) == 2:
                engine.wait(int(parts[1]))
            elif parts[0] == "print" and len(parts) == 2 and parts[1] == "board":
                engine.request_render()
