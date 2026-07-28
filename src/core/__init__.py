# src.core -- thin facade over the root engine/ and shared/models/
# packages (pure game logic, no rendering deps). Deliberately does NOT
# duplicate GameEngine/RuleEngine/board logic: engine/ is also imported
# directly by server/ (the multiplayer server) from its current
# repo-root path, so a second, forked copy here would let the two rule
# implementations silently drift apart. Every name below re-exports an
# existing engine/shared type under this package's own clean surface;
# state_machine.py is the one genuinely new module (a query facade over
# existing GameEngine methods, not new rules).
