from img import Img


def draw_piece_on_copy(board: Img, piece_frame: Img, x: int, y: int) -> Img:
    """Return a copy of `board` with `piece_frame` drawn at (x, y)."""
    canvas = Img()
    canvas.img = board.img.copy()
    piece_frame.draw_on(canvas, x, y)
    return canvas
