from __future__ import annotations

import argparse
import logging
import time

from shared.logger_config import setup_logging
from server.database.sqlite_db_manager import DEFAULT_DB_PATH, init_db
from shared.constants import DEFAULT_HOST
from server.network.server import DEFAULT_PORT, NetworkServer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kung Fu Chess – Network Server Entry Point
# ---------------------------------------------------------------------------
# Starts server.network.server.NetworkServer — the new, room/
# matchmaking-capable socket server (see that module's own docstring
# for how it differs from, and coexists with, server/server.py's
# existing WebSocket-based GameServer, started via
# ``python -m server.server`` instead; this script does not start or
# touch that one).
#
# NetworkServer.start() runs its own accept/client threads in the
# background and returns immediately, so this script's job is just:
# initialize the database, start the server, then block until
# interrupted.
# ---------------------------------------------------------------------------


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Kung Fu Chess network server (rooms + ELO matchmaking, raw TCP sockets)"
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Default: {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Default: {DEFAULT_PORT}")
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to the user-accounts SQLite database. Default: {DEFAULT_DB_PATH}",
    )
    args = parser.parse_args()

    init_db(args.db_path)
    server = NetworkServer(host=args.host, port=args.port, db_path=args.db_path)
    server.start()
    logger.info("Kung Fu Chess network server listening on %s:%d", args.host, args.port)

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
