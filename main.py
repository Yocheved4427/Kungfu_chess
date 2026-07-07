import sys

from src.config import VALID_PIECE_CHARS
from src.board_parser import BoardParser
from src.board_validator import BoardValidator
from src.io_handler import ChessIOHandler


# ---------------------------------------------------------------------------
# Kung Fu Chess – Entry point
# ---------------------------------------------------------------------------
# main() wires the dependency graph and hands control to ChessIOHandler.
# sys.stdin / sys.stdout are only referenced here, keeping all business
# logic free of global-state dependencies.
# ---------------------------------------------------------------------------


def main() -> None:
    parser = BoardParser()
    validator = BoardValidator(valid_chars=VALID_PIECE_CHARS)
    handler = ChessIOHandler(
        reader=sys.stdin,
        writer=sys.stdout,
        parser=parser,
        validator=validator,
    )
    handler.run()


if __name__ == "__main__":
    main()
