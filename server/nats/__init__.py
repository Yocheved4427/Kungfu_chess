# server.nats -- NATS Core pub/sub transport for room-based multiplayer,
# replacing server/network/server.py's raw-TCP transport. Reuses the
# same RealTimeArbiter/GameEngine game logic; only how bytes reach the
# server and how state reaches clients changes.
