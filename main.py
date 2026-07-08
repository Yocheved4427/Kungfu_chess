import sys

from src.core.config import CELL_SIZE, VALID_PIECE_CHARS
from src.engine.board import BoardParser, BoardValidator, BoardValidationError
from src.engine.game import GameEngine
from src.ui.io_handler import ChessIOHandler


def main() -> None:
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