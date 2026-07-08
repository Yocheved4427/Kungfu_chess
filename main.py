import sys

from src.config import VALID_PIECE_CHARS
from src.board_parser import BoardParser
from src.board_validator import BoardValidator, BoardValidationError
from src.io_handler import ChessIOHandler

def main() -> None:
    parser = BoardParser()
    validator = BoardValidator(valid_chars=VALID_PIECE_CHARS)
    handler = ChessIOHandler(
        reader=sys.stdin,
        writer=sys.stdout,
        parser=parser,
        validator=validator,
    )
    
    try:
        handler.run()
    except BoardValidationError as e:
        print(f"ERROR {e}")

if __name__ == "__main__":
    main()