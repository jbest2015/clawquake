# ClawQuake Strategy Loading (Current Behavior)

Last updated: 2026-03-31

## TL;DR

- ClawQuake currently uses the HTTP API as the control plane (`/api/*`).
- Strategy execution is file-based and local to the orchestrator/runner (`agent_runner.py` + `strategies/*.py`).
- There is no MCP strategy transport/library wired into match execution yet.

## Control Plane vs Runtime Plane

### Control Plane (HTTP API)

Use API endpoints to:
- authenticate users
- create API keys
- register bots
- join/leave queue
- read match/leaderboard state

Primary endpoints:
- `POST /api/bots`
- `POST /api/queue/join`
- `GET /api/queue/status`
- `GET /api/matches/{id}`

### Runtime Plane (Strategy Execution)

When a queued match starts:
1. `orchestrator/matchmaker.py` picks queued bots.
2. For each bot, `_get_bot_strategy()` resolves a Python strategy file path from the bot's stored strategy name.
3. `orchestrator/process_manager.py` launches:
   `python orchestrator/agent_runner.py --strategy <path> --name <bot_name> ...`
4. `agent_runner.py` loads strategy module and runs tick loop.

## How Strategy Path Resolution Works Today

Implemented in `orchestrator/matchmaker.py::_get_bot_strategy()`:

1. Read the bot's `strategy` field from the database.
2. Build path:
   `strategies/<strategy>.py`
3. If that file exists, use it.
4. Otherwise fallback to:
   `DEFAULT_STRATEGY` env var (default: `strategies/default.py`)

Examples:
- Bot with strategy `codex` -> `strategies/codex.py`
- Bot with strategy `claude` -> `strategies/claude.py`
- Missing file -> `strategies/default.py` (or env override)

## Control Plane API

`POST /api/bots` accepts:

```json
{"name":"MyBot","strategy":"codex"}
```

Related endpoints:
- `GET /api/strategies`
- `POST /api/bots`
- `PATCH /api/bots/{id}`

The API still does not accept an arbitrary filesystem `strategy_path`. Strategies must exist as files
under `strategies/` and are selected by stem name.

## Recommended Current Workflow

1. Create or update a strategy file in `strategies/`.
2. Register a bot with `strategy="<stem>"`, or patch an existing bot to that strategy.
3. Queue the bot normally.
4. If you keep agent-specific code in `agents/<name>/strategy.py`, add a thin bridge file in `strategies/`.

## Planned Improvement

Planned but not implemented:
- explicit `strategy_path` (or strategy id) per bot in API + DB
- optional MCP-native strategy execution path/library
