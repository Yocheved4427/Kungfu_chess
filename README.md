# Kung Fu Chess

A real-time, **turn-less** chess variant written in Python: pieces move the instant a move is queued and resolve after a per-move travel time, rather than waiting for an opponent's turn — hence "Kung Fu." The project includes a local hot-seat/single-player GUI, an authoritative WebSocket server for real networked multiplayer, and a from-scratch chess rules engine with no external chess library.

Key architectural ideas:

- **Authoritative game server** — in networked play, the server owns the only `GameEngine`/`GameState` that matters. Clients never decide legality themselves; they send a move and render whatever the server broadcasts back.
- **Decoupled domain logic** — `AbstractBoard`/`TextBoard` (`engine/board.py`) is pure board state with zero knowledge of pixels, rendering, or networking. Move legality (`engine/rules.py`, `engine/rule_engine.py`), collision resolution (`realtime/collision_resolver.py`), and rendering (`ui/graphics/`) are all separate layers built on top of it.
- **Asynchronous networking** — the server is `asyncio`/`websockets`-based; the GUI client bridges to it via a background thread running its own event loop, so the existing synchronous, OpenCV-driven render loop didn't need to change shape.
- **Real-time cooldown timers** — every piece that lands or jumps is briefly unselectable (`COOLDOWN_DURATION`), and a move's travel time is proportional to distance (per-cell `MOVE_DURATION`), broken into individually-timed checkpoints so a piece's position can be smoothly interpolated on screen instead of teleporting.

> **Note on this document:** a couple of module paths and library choices mentioned in early planning notes for this project didn't match what was actually built — this README describes the code as it exists in this repository, not those notes. In particular, the WebSocket server lives at `server/server.py` (not `server/game_server.py`), the local persistence layer lives at `server/database.py` (not a top-level `database.py`), and the GUI is OpenCV-only — no Pygame is used anywhere.

---

## Table of Contents

- [System Architecture & Key Features](#system-architecture--key-features)
- [Prerequisites & Installation](#prerequisites--installation)
- [How to Run](#how-to-run)
  - [Local mode (single-player / hot-seat two-player)](#local-mode-single-player--hot-seat-two-player)
  - [Networked two-player demo](#networked-two-player-demo)
  - [Text/CLI pipeline](#textcli-pipeline)
- [Testing & Test Coverage](#testing--test-coverage)
- [Project Structure](#project-structure)
- [Known Limitations](#known-limitations)

---

## System Architecture & Key Features

### Authoritative WebSocket server — `server/server.py`

A single-process `asyncio`/`websockets` server (`GameServer`) that accepts exactly two connections. Each must log in (`{"type": "login", "username": "..."}`) before anything else is possible; the first successful login becomes White, the second Black. Only once both are logged in does the server build the one shared `GameEngine`/`GameState` and start its tick loop — a background task that advances the game clock on a fixed real-time interval (`asyncio.sleep`), independent of client activity. Clients send moves in algebraic notation (`server/algebraic.py` converts to/from this engine's `Position`); the server is the only thing that ever calls `GameEngine.attempt_move`. State changes reach clients two ways: every `GameEvent` the engine fires is serialized (`GameEvent.to_dict()`) and broadcast, and a full board snapshot is broadcast once per tick so a client can always resync even if it missed an individual event.

This server's login is intentionally minimal — a username only, no password, no persistence, no uniqueness check beyond "non-empty and not absurdly long." It is a **separate system** from the local account system described below; the two do not currently share user identities.

### Pure, stateless board logic — `engine/`

`AbstractBoard`/`TextBoard` (`engine/board.py`) model board occupancy only: which piece, if any, sits at each `(row, col)`. Move geometry (`engine/rules.py`, Strategy pattern per piece type), a synchronous rules-validation service (`engine/rule_engine.py`), and the real-time queued-move pipeline (`engine/game.py`'s `GameEngine`) are all separate collaborators built on top of it — `GameEngine` is the single place that ever mutates a board or a `GameState`. Rendering (`ui/graphics/graphics_board_renderer.py`) only ever reads a read-only, point-in-time `GameSnapshot` (`engine/snapshot.py`), never the engine's live internals.

### User persistence & security — `server/database.py`

A local SQLite (`kungfu_chess.db`) persistence layer, independent of the WebSocket server above: user accounts (`users` table — `bcrypt`-hashed passwords, ELO rating) and a `game_history` table (per-game move log and outcome). This is what gates the **local** GUI's login/dashboard screens (`login_view.py`, `dashboard_view.py`) — a separate concern from the WebSocket server's own simple, unauthenticated username login used for networked play. See [Known Limitations](#known-limitations) for where these two systems don't yet connect.

### Event-driven architecture — `ui/bus.py`, `ui/events.py`

`GameEngine` never talks to a renderer, a network connection, or a database directly — it publishes immutable `GameEvent`s (`MoveCompletedEvent`, `GameOverEvent`, `AirborneCaptureEvent`, ...) through a small `Bus` (Observer pattern), and anything that cares subscribes: the local GUI's score/move-history trackers, the WebSocket server's broadcast queue, or a future observer that hasn't been written yet. Every event has a `to_dict()` for JSON serialization, which is what the WebSocket protocol broadcasts.

---

## Prerequisites & Installation

- **Python 3.10+** (developed and tested on Python 3.14).
- A display for the GUI modes (`main_gui.py`) — the text/CLI pipeline (`main.py`) needs no display.

Install dependencies:

```bash
pip install -r requirements.txt
```

This installs everything the project needs:

| Package | Purpose |
|---|---|
| `opencv-python` | All GUI rendering — board, pieces, HUD, login/dashboard screens. No other GUI toolkit is used. |
| `numpy` | Backing arrays for OpenCV image composition. |
| `websockets` | The async WebSocket server and the GUI's network client. |
| `bcrypt` | Password hashing for the local account system (`server/database.py`). |
| `pytest` | Test runner. |
| `pytest-asyncio` | Runs the server's `async def` tests. |

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

There are three independent ways to play, depending on which entry point you launch.

### Local mode (single-player / hot-seat two-player)

No server needed. Launching `main_gui.py` without `--username` shows a local login/registration screen (backed by `server/database.py`), then a dashboard with your ELO/stats and a "Start New Game" button, then the board itself.

```bash
# One player, controlling both colors (practice / hot-seat):
python main_gui.py

# Split-screen hot-seat: White on the left half, Black on the right,
# each logs in (and dashboards) separately before the shared game starts:
python main_gui.py --two-player
```

Useful flags: `--board <path>` (custom starting layout), `--scale <float>` / `--cell-size <int>` (board sizing).

### Networked two-player demo

This is genuine client/server multiplayer: the server owns the only real game; each GUI instance is a thin, non-authoritative client.

**Step 1 — start the server:**

```bash
python -m server.server --host localhost --port 8765
```

**Step 2 — launch Player 1 (becomes White):**

```bash
python main_gui.py --username player1
```

**Step 3 — launch Player 2 (becomes Black):**

```bash
python main_gui.py --username player2
```

`--username` skips the local login/dashboard screens entirely (that's the separate, local-account system described above) and connects straight to the server. `--host`/`--port` override the defaults if the server isn't on `localhost:8765`. A third `--username` instance while two are already connected is rejected with a clear message.

You can also drive the server with the minimal scripted reference client, useful for verifying the server in isolation without opening a GUI window:

```bash
python server/test_client.py <username>
```

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

As of this writing: **974 tests, all passing.**

To check coverage (requires `pytest-cov`, see [Prerequisites](#prerequisites--installation)):

```bash
pytest --cov=. --cov-report=term-missing
```

As of this writing, this reports **90% overall statement coverage** (8,255 statements, 852 missed). Coverage is not uniform by design:

- Pure domain logic (`core/`, `engine/`, `realtime/`, `input/`, `controllers/`) and the WebSocket protocol/algebraic-notation layer (`server/algebraic.py`, `server/server.py`'s message handling) sit at or near **100%**.
- The GUI entry points (`main.py`, `main_gui.py`, `login_view.py`, `dashboard_view.py`) and the game render loops (`ui/game_loop.py`) show low/no coverage from automated tests — these open a real OpenCV window and run an infinite loop, so they're exercised through manual/integration testing rather than `pytest`, not because they're untested.
- `network_client.py`'s background-thread/asyncio internals are similarly verified manually against a live server rather than through the automated suite.

---

## Project Structure

```
Kungfu chess/
├── main.py                  # Text/CLI entry point (stdin script -> stdout board)
├── main_gui.py               # GUI entry point: local modes + --username network mode
├── login_view.py             # Local account login/registration screen (OpenCV)
├── dashboard_view.py         # Post-login lobby: stats, "Start New Game" / "Log Out"
├── network_client.py         # Background-thread WebSocket client for main_gui.py
├── logger_config.py           # Shared logging setup for every entry point
├── requirements.txt
│
├── core/                     # Pure value objects only — no I/O, no business logic
│   ├── config.py              # Tunable constants (durations, piece points, ...)
│   └── models.py              # Color, Position, PendingMove, GameResult, ...
│
├── engine/                   # Domain logic: board, rules, the real-time game engine
│   ├── board.py                # AbstractBoard / TextBoard
│   ├── rules.py                # Per-piece move geometry (Strategy pattern)
│   ├── rule_engine.py          # Synchronous move-legality service
│   ├── game.py                 # GameEngine — the real-time queued-move pipeline
│   ├── game_state.py            # Mutable per-game state (board, clock, pending, ...)
│   ├── game_over.py             # GameOverRule / KingCaptureRule
│   ├── snapshot.py              # Read-only, point-in-time GameSnapshot for rendering
│   ├── score_tracker.py         # Cumulative capture score (snapshot-diffing)
│   └── move_history_tracker.py  # Completed-move log (snapshot-diffing)
│
├── realtime/                 # Real-time-specific collision/timing logic
│   ├── collision_resolver.py    # Friendly mid-route block / airborne interception
│   └── mid_flight_collision.py  # Standalone continuous-time path-crossing math
│
├── input/                    # External-representation <-> engine-type translation
│   ├── board_parser.py          # Text rows -> TextBoard
│   └── board_mapper.py          # Pixel <-> (row, col) coordinate translation
│
├── controllers/
│   └── click_controller.py      # Click semantics (select / switch / attempt move)
│
├── server/                   # Networked multiplayer + local persistence
│   ├── server.py                # Authoritative WebSocket GameServer
│   ├── algebraic.py             # "e2" <-> Position conversion
│   ├── database.py              # SQLite: accounts, ELO, game history (bcrypt)
│   └── test_client.py           # Minimal manual/reference WebSocket client
│
├── ui/                       # Presentation layer
│   ├── events.py                 # GameEvent subclasses + Observer contract
│   ├── bus.py                    # Pub/sub Bus GameEngine publishes through
│   ├── observers.py               # SoundTriggerObserver, GameLifecycleObserver
│   ├── io_handler.py              # main.py's text-pipeline Observer
│   ├── cli.py                     # main_gui.py's argument parsing
│   ├── game_factory.py            # Board loading + fresh GameEngine/GameState
│   ├── game_loop.py                # Local + networked render/input loops
│   └── graphics/
│       ├── graphics_board_renderer.py  # The board/HUD renderer (OpenCV)
│       ├── piece_view.py / piece_state_machine.py / sprite_sequence.py  # Per-piece animation
│       ├── motion.py                    # Smooth in-transit position interpolation
│       ├── game_over_animation.py       # Fading game-over overlay
│       ├── asset_loader.py              # Sprite sheet loading/caching
│       └── img.py                       # Thin OpenCV image wrapper
│
├── assets/
│   ├── board.png
│   └── pieces3/                  # Active sprite set ([color][piece]/states/.../sprites/*.png)
│
└── tests/
    ├── unit/                      # One test file per module, ~40 files
    └── integration/
        └── test_chess_pipeline.py # End-to-end text-pipeline tests
```

---

## Known Limitations

- **Two separate login/user systems.** The local GUI's account system (`server/database.py`, bcrypt, ELO, game history) and the WebSocket server's networked login (`server/server.py`, username-only) are independent today — logging in locally and playing over the network don't share an identity.
- **Game results aren't persisted yet.** Nothing currently calls `save_game_result()`/`update_elo()` when a local game actually ends, so the dashboard's "Games Played/Wins/Losses" will read as zero until that wiring is added; ELO itself is a real, working column, just never updated in practice yet.
- **Networked rendering is bare-board only.** The WebSocket protocol's snapshot message carries board occupancy, the clock, and the game-over state, but no per-piece pending-move/airborne/cooldown detail — so networked play doesn't (yet) show the smooth in-transit gliding, cooldown timers, or score/move-history panels that local mode has. Extending the wire protocol to carry that detail is a natural next step.
- **No matchmaking/rooms/reconnection.** The server supports exactly one game between exactly two connections at a time; a disconnect frees its colour slot for a new connection, but there's no way to resume an in-progress game as the same identity.
