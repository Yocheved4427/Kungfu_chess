from __future__ import annotations
from typing import TextIO

from src.board_parser import BoardParser
from src.board_validator import BoardValidator

class ChessIOHandler:
    def __init__(
        self,
        reader: TextIO,
        writer: TextIO,
        parser: BoardParser,
        validator: BoardValidator,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._parser = parser
        self._validator = validator

    def run(self) -> None:
        raw_lines = self._reader.readlines()
        board_lines = []
        in_board = False
        
        for line in raw_lines:
            clean_line = line.strip()
            if clean_line == "Board:":
                in_board = True
                continue
            if clean_line == "Commands:":
                in_board = False
                continue
                
            if in_board:
                board_lines.append(line.rstrip('\r\n'))
                
        board = self._parser.parse(board_lines)
        self._validator.validate(board.get_rows())
        self._writer.write(board.render() + "\n")