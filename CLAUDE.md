# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ClawQuake is an AI bot combat arena where autonomous agents compete in Quake 3 (OpenArena/QuakeJS) deathmatches. The platform handles matchmaking, ELO ranking, tournament brackets, live spectating via HLS streaming, and a web dashboard.

## Commands

### Running Tests
```bash
pytest tests/ -v              # All tests
pytest tests/test_matchmaker.py -v   # Single test file
pytest tests/test_matchmaker.py::test_name -v  # Single test
```

Tests use in-memory SQLite and mock RCON. No Docker or game server needed. The `tests/conftest.py` sets `JWT_SECRET`, `RCON_PASSWORD`, and `INTERNAL_SECRET` env vars automatically.

### Running Locally (without Docker)
```bash
cd orchestrator
export JWT_SECRET=$(openssl rand -hex 32)
export RCON_PASSWORD=test
export INTERNAL_SECRET=test
uvicorn main:app --reload --port 8000
```

### Running with Docker
```bash
docker-compose up --build                    # Local dev (1 game server)
docker-compose -f docker-compose.multi.yml up --build  # Multi-server (3 game servers)
```

### Running a Bot Manually
```bash
python agent_runner.py \
  --strategy strategies/default.py \
  --name "MyBot" \
  --server ws://localhost:27960 \
  --duration 120 \
  --results results/latest.json
```

## Architecture

Four Docker services compose the platform:

```
[Browser] → [nginx :80] → [orchestrator :8000 (FastAPI + SQLite)]
                        → [gameserver :27960 (QuakeJS/ioquake3)]
                        → [spectator :8080 (Xvfb + FFmpeg → HLS)]
```

### Orchestrator (`orchestrator/`)
FastAPI backend. Entry point is `main.py`. Handles auth (JWT + API keys), bot registration, matchmaking queue, ELO calculation, RCON server pool, WebSocket event broadcasting, and bot subprocess management. SQLAlchemy models in `models.py`.

### Bot Runtime (`bot/` + `agent_runner.py`)
`agent_runner.py` is the CLI entry point spawned by the orchestrator's `process_manager.py` as a subprocess for each bot in a match. It loads a strategy `.py` file, connects to the QuakeJS server via WebSocket using the Q3 protocol client (`bot/client.py`), and runs a tick loop calling `strategy.tick()` each frame. Supports hot-reload of strategy files.

### Strategies (`strategies/`)
Python files implementing bot behavior. Each defines `STRATEGY_NAME`, `STRATEGY_VERSION`, `on_spawn(ctx)`, and `async tick(bot, game, ctx)`. Strategy resolution in `orchestrator/matchmaker.py::_get_bot_strategy()` tries `strategies/<normalized_bot_name>.py`, falling back to `strategies/default.py`.

### Agent Strategies (`agents/`)
Named agent directories (e.g., `agents/claude/`, `agents/antigravity/`) with versioned `strategy.py` files for specific AI agents competing in the arena.

### Web UI (`web/`)
Vanilla HTML/CSS/JS frontend. Dashboard with live stats, spectator view (QuakeJS iframe), tournament brackets, replay viewer, API docs page.

## Key Data Flow: Match Lifecycle

1. User registers → gets JWT
2. Creates API key (required — matchmaker checks owner has active key)
3. Registers bot via API
4. Joins matchmaking queue
5. `matchmaker.run_loop()` (async background task) pairs waiting bots
6. `process_manager.launch_match()` spawns `agent_runner.py` subprocesses
7. Bots connect to game server, play for `MATCH_DURATION` seconds
8. Process manager detects exits → matchmaker finalizes (ELO update, winner)

## Environment Variables

Required (see `.env.example`):
- `JWT_SECRET` — JWT signing key
- `RCON_PASSWORD` — Quake server RCON password
- `INTERNAL_SECRET` — Bot result reporting auth (default: `changeme`)

Optional:
- `MATCH_DURATION` — Seconds per match (default: 120)
- `QUEUE_POLL_INTERVAL` — Matchmaker poll frequency (default: 5s)
- `GAME_SERVER_HOST` — Game server hostname (set to `gameserver-1` in Docker)
- `GAME_SERVER_URLS` — WebSocket URLs for bot connections

## Test Infrastructure

- Tests add `orchestrator/` to `sys.path` so orchestrator modules import directly (e.g., `from models import Base`)
- In-memory SQLite via `db` fixture; `db_factory` fixture for classes that create their own sessions
- `mock_rcon` fixture provides a mock RCON pool
- Helper functions: `create_test_user()`, `create_test_bot()`, `queue_bot()` in `conftest.py`

## Important Gotchas

- **Protocol 71 vs 68**: QuakeJS uses protocol 71. Must set `sv_pure 0` and skip legacy `begin` command for protocol 71 servers. Otherwise bots connect but never spawn.
- **Docker path resolution**: `os.path.dirname(__file__)` + `..` breaks when files are copied flat into `/app/`. Use `os.path.abspath()`.
- **Docker networking**: Inside containers, `localhost` is that container. Other containers are reached by service name (e.g., `gameserver-1`).
- **Bot name uniqueness is global**: `BotDB.name` has `unique=True` across all users.
- **API key required for matches**: `_owner_has_active_key()` check means bots won't launch without an active, non-expired API key.
- **Game servers only work on x86_64**: OpenArena QVM is incompatible with ARM64.
- **Production uses `docker-compose` (hyphenated)**: Older Docker version on prod server.
