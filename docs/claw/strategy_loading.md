# ClawQuake Strategy Loading (Current Behavior)

Last updated: 2026-02-09

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
2. For each bot, `_get_bot_strategy()` resolves a Python strategy file path.
3. `orchestrator/process_manager.py` launches:
   `python orchestrator/agent_runner.py --strategy <path> --name <bot_name> ...`
4. `agent_runner.py` loads strategy module and runs tick loop.

## How Strategy Path Resolution Works Today

Implemented in `orchestrator/matchmaker.py::_get_bot_strategy()`:

1. Build convention path from bot name:
   `strategies/<bot_name_lower_with_spaces_as_underscores>.py`
2. If that file exists, use it.
3. Otherwise fallback to:
   `DEFAULT_STRATEGY` env var (default: `strategies/default.py`)

Examples:
- Bot name `CodexMatch1` -> `strategies/codexmatch1.py`
- Bot name `Claude Match 1` -> `strategies/claude_match_1.py`
- Missing file -> `strategies/default.py` (or env override)

## Important Current Limitation

`POST /api/bots` only accepts:

```json
{"name":"MyBot"}
```

There is currently no per-bot `strategy_path` field in the DB/API.

## Recommended Current Workflow

1. Pick a bot name that maps to your intended strategy filename.
2. Create that strategy file in `strategies/`.
3. Register bot via API with matching name.
4. Queue bot normally.

## Planned Improvement

Planned but not implemented:
- explicit `strategy_path` (or strategy id) per bot in API + DB
- optional MCP-native strategy execution path/library
