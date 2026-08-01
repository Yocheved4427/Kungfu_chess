# server.spectator -- the Spectator Gateway: subscribes to the lightweight
# Redis diff stream server/nats/game_server.py publishes and broadcasts it
# (delayed, anti-cheat) to spectator WebSockets. Owns all spectator
# connection lifecycle; the Game Server has no knowledge of it.
