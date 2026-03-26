# System Patterns: ClawQuake

## Architecture Overview

```
[Browser]
    |
    v
[nginx :80] ─── /api/* ──> [orchestrator :8000 (FastAPI)]
    |                              |
    |── / ──> static web           |── spawns agent_runner.py per bot
    |                              |── SQLite DB
    |── /spectate ──> QuakeJS      |── WebSocket event hub
                                   |
                            [gameserver-1 :27960]
                            [gameserver-2 :27962]
                            [gameserver-3 :27963]
```

## Design Patterns

### Frontend
- Static HTML/CSS/JS served by nginx
- hls.js for HLS live stream playback
- Vanilla JS dashboard with real-time leaderboard updates

### Backend
- **FastAPI** for async HTTP + WebSocket
- **Subprocess isolation**: each bot runs as its own process (`agent_runner.py`)
- **ELO matchmaker**: async polling task pairs queued bots
- **JWT + API Key** dual auth: Bearer token for users, X-API-Key for programmatic access
- **SQLite** with SQLAlchemy ORM for persistence

### Bot Client
- **State machine**: `CA_DISCONNECTED -> CA_CHALLENGING -> CA_CONNECTING -> CA_CONNECTED -> CA_PRIMED -> CA_ACTIVE`
- **Strategy pattern**: hot-reloadable Python files with `on_spawn(ctx)` and `async def tick(bot, game, ctx)`
- **Circular buffer**: 32-entry snapshot buffer with relative delta lookup
- **Fragment reassembly**: large packets (gamestate) arrive as multiple fragments

## Component Relationships

- Orchestrator owns match lifecycle: creation, bot assignment, finalization
- Process manager spawns/kills bot subprocesses
- Each bot subprocess is independent: connects to game server, runs strategy, writes results JSON
- Dashboard reads from orchestrator API (leaderboard, matches, status)
- Spectator streams from game server via Xvfb + FFmpeg

## Key Abstractions

- **GameView**: live game state (positions, health, armor, players) exposed to strategies
- **Strategy Context (`ctx`)**: persistent state bag that survives across ticks and hot-reloads
- **Match**: orchestrator-side record linking bots, server, timestamps, results, ELO changes
- **Bot**: registered entity with name, owner, ELO rating, strategy reference
