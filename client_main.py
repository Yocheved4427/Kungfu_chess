from __future__ import annotations

import argparse
import logging

from logger_config import setup_logging
from shared.constants import DEFAULT_HOST
from server.network.server import DEFAULT_PORT
from client.network.client import NetworkClient
from client.ui.app.online_coordinator import OnlineCoordinator
from client.ui.screens.home_screen import run_home_screen
from client.ui.screens.online_game_screen import run_online_game_screen
from client.ui.screens.room_screen import run_room_screen
from client.ui.screens.screen_manager import Screen, ScreenManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kung Fu Chess – Online Client Entry Point
# ---------------------------------------------------------------------------
# Connects to server/network/server.py's NetworkServer (rooms + ELO
# matchmaking over raw TCP sockets, framed via shared.protocol — see
# that module's own docstring for how it differs from, and coexists
# with, server/server.py's older WebSocket-based GameServer, which
# main_gui.py's --username mode already talks to instead). This script
# does not start or touch that older pipeline; run main_gui.py for it.
#
# Screen loop: each run_*_screen() call BLOCKS until its own screen
# transition fires (see client.ui.screens.screen_manager.Screen's own
# legal-transition table), then returns control here to hand off to
# whichever screen ScreenManager.current now names -- this loop just
# keeps dispatching to that, so the whole app's flow is exactly the
# transition graph: Main Menu -> Login -> Lobby -> Game -> Lobby | Main
# Menu -> ...
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kung Fu Chess online client")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Default: {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Default: {DEFAULT_PORT}")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = _parse_args()

    client = NetworkClient(args.host, args.port)
    if not client.connect(timeout=5.0):
        logger.error("Could not connect to %s:%d", args.host, args.port)
        return

    screens = ScreenManager()
    coordinator = OnlineCoordinator(client, screens)

    try:
        while True:
            if screens.current is Screen.MAIN_MENU:
                screens.transition_to(Screen.LOGIN)
                continue

            if screens.current is Screen.LOGIN:
                if not run_home_screen(coordinator):
                    break  # player cancelled -- quit the app entirely
                continue

            if screens.current is Screen.LOBBY:
                run_room_screen(coordinator)
                continue

            if screens.current is Screen.GAME:
                run_online_game_screen(coordinator)
                continue

            break  # unreachable -- every Screen member is handled above
    finally:
        client.close()


if __name__ == "__main__":
    main()
