# Kung Fu Chess

A real-time, **turn-less** chess variant written in Python: pieces move the instant a move is queued and resolve after a per-move travel time, rather than waiting for an opponent's turn — hence "Kung Fu." The project includes a local hot-seat/single-player GUI, two independent networked-multiplayer implementations, and a from-scratch chess rules engine with no external chess library.

Key architectural ideas:

- **Authoritative game server** — in networked play, the server owns the only `GameEngine`/`GameState` that matters. Clients never decide legality themselves; they send a move and render whatever the server broadcasts back.
- **Decoupled domain logic** — `AbstractBoard`/`TextBoard` (`shared/models/board.py`) is pure board state with zero knowledge of pixels, rendering, or networking. Move legality (`engine/rules.py`, `engine/rule_engine.py`), collision resolution (`realtime/collision_resolver.py`), and rendering (`src/rendering/`) are all separate layers built on top of it.
- **Asynchronous networking** — `server/server.py` is `asyncio`/`websockets`-based; the GUI client bridges to it via a background thread running its own event loop, so the existing synchronous, OpenCV-driven render loop didn't need to change shape.
- **Real-time cooldown timers** — every piece that lands or jumps is briefly unselectable (`COOLDOWN_DURATION`), and a move's travel time is proportional to distance (per-cell `MOVE_DURATION`), broken into individually-timed checkpoints so a piece's position can be smoothly interpolated on screen instead of teleporting.

---

## Table of Contents

- [System Architecture & Key Features](#system-architecture--key-features)
- [Prerequisites & Installation](#prerequisites--installation)
- [How to Run](#how-to-run)
  - [Local mode](#local-mode)
  - [Networked play (WebSocket demo)](#networked-play-websocket-demo)
  - [Networked play (room/matchmaking demo)](#networked-play-roommatchmaking-demo)
  - [Text/CLI pipeline](#textcli-pipeline)
- [Testing & Test Coverage](#testing--test-coverage)
- [Project Structure](#project-structure)
- [Known Limitations](#known-limitations)

---

## System Architecture & Key Features

### Pure, stateless board logic — `shared/`, `core/`, `engine/`

`AbstractBoard`/`TextBoard` (`shared/models/board.py`) model board occupancy only: which piece, if any, sits at each `(row, col)`. `core/models.py` holds the pure value objects built on top of it (`PendingMove`, `PendingJump`, `GameResult`, ...). Move geometry (`engine/rules.py`, Strategy pattern per piece type), a synchronous rules-validation service (`engine/rule_engine.py`), and the real-time queued-move pipeline (`engine/game.py`'s `GameEngine`) are all separate collaborators built on top of it — `GameEngine` is the single place that ever mutates a board or a `GameState`. Rendering (`src/rendering/renderer.py`) only ever reads a read-only, point-in-time `GameSnapshot` (`engine/snapshot.py`), never the engine's live internals.

### Two local-play entry points — `src/main.py` and `ui/main_gui.py`

There are two ways to play locally, deliberately kept separate:

- **`src/main.py`** — the clean, local-only game: single-player (hot-seat) or split-screen `--two-player`, no accounts, no networking at all. `src/core/` is a thin facade over `engine/`/`shared/models/` (not a second rule implementation — it re-exports the same types the server uses), and `src/rendering/`/`src/utils/` hold the OpenCV presentation layer.
- **`ui/main_gui.py`** — the older, hybrid entry point: local play gated behind a local login/dashboard (see below), *plus* an alternate `--username` mode that connects to `server/server.py` as a real networked client instead of playing locally.

### Authoritative WebSocket server — `server/server.py`

A single-process `asyncio`/`websockets` server (`GameServer`) that accepts exactly two connections. Each must log in (`{"type": "login", "username": "..."}`) before anything else is possible; the first successful login becomes White, the second Black. Only once both are logged in does the server build the one shared `GameEngine`/`GameState` and start its tick loop — a background task that advances the game clock on a fixed real-time interval (`asyncio.sleep`), independent of client activity. Clients send moves in algebraic notation (`server/algebraic.py` converts to/from this engine's `Cell`); the server is the only thing that ever calls `GameEngine.attempt_move`. State changes reach clients two ways: every `GameEvent` the engine fires is serialized (`GameEvent.to_dict()`) and broadcast, and a full board snapshot is broadcast once per tick so a client can always resync even if it missed an individual event.

This server's login is intentionally minimal — a username only, no password, no persistence, no uniqueness check beyond "non-empty and not absurdly long." It is a **separate system** from the local account system described below; the two do not currently share user identities.

### A second, independent multiplayer path — `server/network/server.py` + `client/`

A separate, newer implementation: a raw-TCP server (`NetworkServer`, framed messages from `shared/protocol/`) with real room creation/joining and ELO-windowed matchmaking (`server/services/room_service.py`, `server/services/matchmaking_service.py`), paired with its own client package (`client/`, entry point `client/main.py`). It reuses the same `RealTimeArbiter`/`GameEngine` machinery as `server/server.py` (see `server/game/real_time_arbiter.py`) but is otherwise a fully independent protocol and codebase — **the two servers are not interchangeable and a client for one cannot talk to the other.**

### User persistence & security — `server/database/sqlite_db_manager.py`

A local SQLite (`kungfu_chess.db`, gitignored) persistence layer, independent of both servers above: user accounts (`users` table — `bcrypt`-hashed passwords, ELO rating) and a `game_history` table (per-game move log and outcome). This is what gates `ui/main_gui.py`'s local login/dashboard screens (`ui/login_view.py`, `ui/dashboard_view.py`) — a separate concern from either server's own login. See [Known Limitations](#known-limitations) for where these systems don't yet connect.

### Event-driven architecture — `ui/bus.py`, `ui/events.py`

`GameEngine` never talks to a renderer, a network connection, or a database directly — it publishes immutable `GameEvent`s (`MoveCompletedEvent`, `GameOverEvent`, `AirborneCaptureEvent`, ...) through a small `Bus` (Observer pattern), and anything that cares subscribes: the local GUI's score/move-history trackers, a server's broadcast queue, or a future observer that hasn't been written yet. Every event has a `to_dict()` for JSON serialization, which is what both WebSocket/TCP protocols broadcast.

---

## Prerequisites & Installation

- **Python 3.10+** (developed and tested on Python 3.14).
- A display for the GUI modes (`src/main.py`, `ui/main_gui.py`) — the text/CLI pipeline (`main.py`) needs no display.

Install dependencies:

```bash
pip install -r requirements.txt
```

This installs everything the project needs:

| Package | Purpose |
|---|---|
| `opencv-python` | All GUI rendering — board, pieces, HUD, login/dashboard screens. No other GUI toolkit is used. |
| `numpy` | Backing arrays for OpenCV image composition. |
| `websockets` | The async WebSocket server (`server/server.py`) and its GUI network client. |
| `bcrypt` | Password hashing for the local account system (`server/database/sqlite_db_manager.py`). |
| `pytest` | Test runner. |
| `pytest-asyncio` | Runs the async server tests. |

`sqlite3` (local persistence) is part of the Python standard library — nothing to install.

If you only want a subset manually rather than the full `requirements.txt`:

```bash
pip install opencv-python numpy websockets bcrypt pytest pytest-asyncio
```

To also run the coverage command in [Testing & Test Coverage](#testing--test-coverage), additionally install:

```bash
pip install pytest-cov
```

---

## How to Run

There are four independent ways to play, depending on which entry point you launch. All commands below are run from the repo root.

### Local mode

No server needed, no accounts. The clean, local-only entry point:

```bash
# One player, controlling both colors (practice / hot-seat):
python -m src.main

# Split-screen hot-seat: White on the left half, Black on the right:
python -m src.main --two-player
```

Useful flags: `--board <path>` (custom starting layout), `--scale <float>` / `--cell-size <int>` (board sizing).

The older entry point, `python -m ui.main_gui` (with the same flags), does the same local play but behind a local login/dashboard gate first (SQLite-backed accounts, ELO/stats) — use this one if you want that account layer; use `src.main` if you just want to play.

### Networked play (WebSocket demo)

Genuine client/server multiplayer against `server/server.py`: the server owns the only real game; each GUI instance is a thin, non-authoritative client.

**Step 1 — start the server:**

```bash
python -m server.server --host localhost --port 8765
```

**Step 2 — launch Player 1 (becomes White):**

```bash
python -m ui.main_gui --username player1
```

**Step 3 — launch Player 2 (becomes Black):**

```bash
python -m ui.main_gui --username player2
```

`--username` skips the local login/dashboard screens entirely (that's the separate, local-account system described above) and connects straight to the server. `--host`/`--port` override the defaults if the server isn't on `localhost:8765`. A third `--username` instance while two are already connected is rejected with a clear message.

You can also drive the server with the minimal scripted reference client, useful for verifying the server in isolation without opening a GUI window:

```bash
python server/test_client.py <username>
```

### Networked play (room/matchmaking demo)

The second, independent multiplayer path (`server/network/server.py` + `client/`) — real rooms and ELO-windowed matchmaking over raw TCP.

**Step 1 — start the server:**

```bash
python -m server.server_main --host localhost --port 8766
```

**Step 2 — launch one or more clients**, each in its own terminal:

```bash
python -m client.main --host localhost --port 8766
```

Each client walks through its own home/room/lobby screens (register or log in, then create/join a room or queue for a matched opponent) rather than taking a username as a launch flag.

### Text/CLI pipeline

A separate, display-free entry point that reads a board and a line-oriented command script from stdin and prints the resulting board as text — used by the automated grading pipeline this engine was originally built against, and handy for quick scripted checks:

```bash
python main.py < path/to/script.txt
```

---

## Testing & Test Coverage

Run the full unit + integration test suite:

```bash
pytest
```

As of this writing: **1010 tests, all passing.**

To check coverage (requires `pytest-cov`, see [Prerequisites](#prerequisites--installation)):

```bash
pytest --cov=. --cov-report=term-missing
```

Coverage is not uniform by design — run the command above for current numbers, but expect the shape to be:

- Pure domain logic (`shared/`, `core/`, `engine/`, `realtime/`, `input/`, `controllers/`) and the WebSocket protocol/algebraic-notation layer (`server/algebraic.py`, `server/server.py`'s message handling) at or near **100%**.
- The GUI entry points (`main.py`, `src/main.py`, `ui/main_gui.py`, `ui/login_view.py`, `ui/dashboard_view.py`) and the game render loops (`ui/game_loop.py`) show low/no coverage from automated tests — these open a real OpenCV window and run an infinite loop, so they're exercised through manual/integration testing rather than `pytest`, not because they're untested.
- `ui/network_client.py`'s background-thread/asyncio internals are similarly verified manually against a live server rather than through the automated suite.

---

## Project Structure

```
Kungfu chess/
├── main.py                     # Text/CLI entry point (stdin script -> stdout board)
├── requirements.txt
│
├── shared/                     # Pure value objects/protocol -- zero I/O, imported by every layer,
│   │                           #   including the server (nothing here ever moves)
│   ├── constants.py              # Tunable durations, piece points, board defaults
│   ├── logger_config.py          # Shared logging setup for every entry point
│   ├── models/                    # AbstractBoard/TextBoard, Cell, Color, PieceType
│   └── protocol/                  # Framed wire protocol for server/network/server.py + client/
│
├── core/
│   └── models.py                 # PendingMove, PendingJump, GameResult, same_color, ...
│
├── engine/                     # Domain logic: rules, the real-time game engine
│   ├── rules.py / rule_engine.py   # Per-piece move geometry + synchronous legality service
│   ├── game.py                     # GameEngine -- the real-time queued-move pipeline
│   ├── game_state.py / snapshot.py # Mutable per-game state / read-only point-in-time snapshot
│   ├── score_tracker.py / move_history_tracker.py  # Snapshot-diffing trackers
│   └── ...                          # board_renderer.py, cooldown.py, game_over.py, geometry.py, ...
│
├── realtime/                   # Real-time-specific collision/timing logic
│   ├── collision_resolver.py      # Friendly mid-route block / airborne interception
│   └── mid_flight_collision.py    # Standalone continuous-time path-crossing math
│
├── input/                      # External-representation <-> engine-type translation
│   ├── board_parser.py            # Text rows -> TextBoard
│   └── board_mapper.py            # Pixel <-> (row, col) coordinate translation
│
├── controllers/
│   └── click_controller.py        # Click semantics (select / switch / attempt move)
│
├── ui/                          # Presentation/orchestration layer: the CLI pipeline's Observer,
│   │                            #   plus the older, hybrid (local + --username networked) GUI
│   ├── events.py / bus.py          # GameEvent subclasses + Observer contract / pub-sub Bus
│   ├── observers.py                 # SoundTriggerObserver, GameLifecycleObserver
│   ├── io_handler.py                # main.py's text-pipeline Observer
│   ├── game_factory.py              # Board loading + fresh GameEngine/GameState
│   ├── cli.py                       # main_gui's argument parsing
│   ├── game_loop.py                  # Local + networked (--username) render/input loops
│   ├── main_gui.py                   # GUI entry point: local modes + --username network mode
│   ├── login_view.py / dashboard_view.py  # Local account login/registration + post-login lobby
│   └── network_client.py             # Background-thread WebSocket client for server/server.py
│
├── src/                         # The newer, CLEAN local-only game package -- no accounts, no
│   │                            #   networking, deliberately separate from ui/'s hybrid entry point
│   ├── main.py                    # Local-only entry point: single-player + --two-player
│   ├── core/                       # Thin facade over engine/ + shared/models/ -- re-exports the
│   │                               #   SAME types the server uses, no duplicated rules
│   ├── rendering/                  # OpenCV rendering (renderer.py, input_handler.py, img.py,
│   │                               #   motion.py, piece_state_machine.py, piece_view.py, ...)
│   │   └── demos/                    # Standalone manual sprite-animation demo scripts
│   └── utils/
│       └── asset_manager.py         # Sprite sheet loading/caching
│
├── server/                      # Two independent multiplayer servers + local persistence
│   ├── server.py                   # (1) Authoritative WebSocket GameServer -- python -m server.server
│   ├── algebraic.py                  #     "e2" <-> Cell conversion
│   ├── test_client.py                #     Minimal manual/reference WebSocket client
│   ├── server_main.py               # (2) Entry point -- python -m server.server_main
│   ├── network/server.py             #     Raw-TCP, shared.protocol-framed NetworkServer + rooms
│   ├── game/                         #     RealTimeArbiter, move_scheduler, collision_service, rules/
│   ├── services/                     #     auth_service, matchmaking_service, room_service
│   └── database/
│       └── sqlite_db_manager.py     # SQLite: accounts, ELO, game history (bcrypt) -- backs ui/login_view.py
│
├── client/                      # The room/matchmaking TCP client, paired with server/network/server.py
│   ├── main.py                     # Entry point -- python -m client.main
│   ├── network/client.py
│   └── ui/                          # screens/ (home, room, online_game), animation/, app/online_coordinator.py
│
├── assets/
│   ├── board.png
│   └── pieces1/, pieces2/, pieces3/  # Sprite sets ([color][piece]/states/.../sprites/*.png) -- pieces3 is active
│
└── tests/
    ├── unit/                      # One test file per module, ~40 files
    └── integration/
        ├── test_chess_pipeline.py    # End-to-end text-pipeline tests
        └── test_server_websocket.py  # End-to-end WebSocket server tests
```

---

## Known Limitations

- **Two separate login/user systems.** The local GUI's account system (`server/database/sqlite_db_manager.py`, bcrypt, ELO, game history) and the WebSocket server's networked login (`server/server.py`, username-only) are independent today — logging in locally and playing over the network don't share an identity. The room/matchmaking server (`server/network/server.py`) has its own third account flow via `server/services/auth_service.py`, also independent of the other two.
- **Game results aren't persisted from local play yet.** Nothing currently calls `save_game_result()`/`update_elo()` when a `src.main`/`ui.main_gui` local game actually ends, so the dashboard's "Games Played/Wins/Losses" will read as zero until that wiring is added; ELO itself is a real, working column, just never updated from local play in practice yet.
- **`server/server.py`'s networked rendering is bare-board only.** Its snapshot message carries board occupancy, the clock, and the game-over state, but no per-piece pending-move/airborne/cooldown detail — so that path doesn't (yet) show the smooth in-transit gliding, cooldown timers, or score/move-history panels that local mode has. Extending the wire protocol to carry that detail is a natural next step.
- **`server/server.py` supports exactly one game at a time**, with no matchmaking/rooms/reconnection — a disconnect frees its colour slot for a new connection, but there's no way to resume an in-progress game as the same identity. (The separate `server/network/server.py` path does have rooms and matchmaking, per above.)
