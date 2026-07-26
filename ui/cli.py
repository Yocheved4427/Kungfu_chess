from __future__ import annotations

import argparse
import logging
import pathlib

from shared.constants import DEFAULT_HOST, DEFAULT_PORT

logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kung Fu Chess GUI")
    parser.add_argument(
        "--board",
        type=pathlib.Path,
        default=None,
        help=(
            "Path to a text file with a custom starting board layout "
            "(same row format as STANDARD_BOARD_ROWS). Falls back to the "
            "standard layout if omitted, unreadable, or invalid."
        ),
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help=(
            "Scale factor applied to the default cell size (the size "
            "main() would otherwise derive from board.png's own pixel "
            "dimensions). Ignored if --cell-size is also given. Default: 1.0."
        ),
    )
    parser.add_argument(
        "--cell-size",
        type=int,
        default=None,
        help=(
            "Exact pixel size of one board cell. Wins over --scale if "
            "both are given (a warning is logged noting --scale was "
            "ignored). Default: derived from board.png."
        ),
    )
    parser.add_argument(
        "--two-player",
        action="store_true",
        help=(
            "Split-screen two-player mode: White plays the left half, "
            "Black the right half, each with independent click/selection "
            "state and restricted to their own colour. Single-player "
            "mode (the default) is unchanged."
        ),
    )
    parser.add_argument(
        "--username",
        default=None,
        help=(
            "Connect to a running server/server.py WebSocket server as "
            "this username instead of launching a local game -- see "
            "network_client.py/ui.game_loop._run_network_player. Skips "
            "the local login_view.py/dashboard_view.py screens entirely "
            "(server/server.py's login is username-only, unrelated to "
            "the local database.py accounts those use). --board/"
            "--two-player are ignored in this mode: the board comes from "
            "the server, and each --username invocation is one player --"
            "run it twice (see main_gui.py's own module docstring) for "
            "two players."
        ),
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Server hostname for --username's network mode. Default: {DEFAULT_HOST}.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=(
            f"Server port for --username's network mode. Default: {DEFAULT_PORT} "
            "(shared.constants.DEFAULT_PORT -- the same value server/server.py itself defaults to)."
        ),
    )
    return parser.parse_args()


def _resolve_cell_size(args: argparse.Namespace, default_cell_size: int) -> int:
    """Return the cell size (px) to render at, per --cell-size/--scale.

    --cell-size wins outright when given — --scale is ignored, with a
    warning logged iff a non-default --scale was also given (so silently
    dropping it isn't a total surprise). Otherwise, --scale multiplies
    *default_cell_size*.
    """
    if args.cell_size is not None:
        if args.scale != 1.0:
            logger.warning(
                "Both --cell-size (%d) and --scale (%.3g) were given; "
                "--cell-size wins and --scale is ignored.",
                args.cell_size,
                args.scale,
            )
        return args.cell_size
    return round(default_cell_size * args.scale)
