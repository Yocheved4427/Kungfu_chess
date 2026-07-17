#https://github.com/Yocheved4427/Kungfu_chess
import sys

from core.config import CELL_SIZE, VALID_PIECE_CHARS
from engine.board_validator import BoardValidator, BoardValidationError
from engine.game import GameEngine
from input.board_parser import BoardParser
from logger_config import setup_logging
from ui.io_handler import ChessIOHandler


def main() -> None:
    setup_logging()

    parser = BoardParser()
    validator = BoardValidator(valid_chars=VALID_PIECE_CHARS)

    def engine_factory(board):
        return GameEngine(board, cell_size=CELL_SIZE)

    handler = ChessIOHandler(
        reader=sys.stdin,
        writer=sys.stdout,
        parser=parser,
        validator=validator,
        engine_factory=engine_factory,
    )

    try:
        handler.run()
    except BoardValidationError as e:
        print(f"ERROR {e}")


if __name__ == "__main__":
    main()