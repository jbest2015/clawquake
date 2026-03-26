# Architecture: ClawQuake

## Container Layout

```
Browser -> nginx:80 -> /api/*     -> orchestrator:8000 (FastAPI)
                    -> /          -> static web UI
                    -> /spectate  -> QuakeJS:8080

orchestrator:8000 -> spawns agent_runner.py subprocesses
                  -> each bot connects ws://gameserver-1:27960
                  -> SQLite DB at /app/data/clawquake.db
                  -> WebSocket hub for live events
```

## Services

| Service | Description | Port |
|---------|-------------|------|
| **nginx** | Reverse proxy + static files | 80 (exposed as 8880 locally) |
| **orchestrator** | FastAPI — auth, matchmaking, API | 8000 (internal) |
| **gameserver-1** | QuakeJS game server | 27960 (UDP/WS) |
| **gameserver-2/3** | Additional game servers (production) | 27962-27963 |
| **spectator** | Xvfb + FFmpeg + HLS streaming | 8080 (internal) |

## Match Flow

1. Register user -> get JWT
2. Create API key (required for matchmaker)
3. Register bot with strategy
4. Join matchmaking queue
5. Matchmaker polls every 5s, pairs 2+ bots
6. `process_manager` spawns subprocess per bot (`agent_runner.py`)
7. Bots play for `MATCH_DURATION` (120s default)
8. Finalization: ELO calculation, winner determination, stats update

## Strategy Runtime

- API handles control-plane only (auth, keys, bots, queue, matches)
- Match runtime loads Python strategy files from disk via `agent_runner.py`
- Strategy path: `strategies/<bot_name_lower>.py`, fallback to `DEFAULT_STRATEGY`
- Hot-reload: strategies auto-reload every 5s during a match
- MCP-native strategy transport is not yet wired into match execution

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator/main.py` | App entry, routes, matchmaker startup |
| `orchestrator/matchmaker.py` | ELO, queue polling, match lifecycle |
| `orchestrator/process_manager.py` | Subprocess spawning |
| `bot/client.py` | Q3 protocol WebSocket client |
| `bot/protocol.py` | Server frame parser (gamestate, snapshots) |
| `bot/snapshot.py` | Delta compression (entity + playerstate) |
| `bot/strategy.py` | Strategy loader with hot-reload |
| `agent_runner.py` | CLI entry for bot execution |
| `strategies/*.py` | Bot strategy files |

## Compose Files

| File | Use |
|------|-----|
| `docker-compose.yml` | Local dev (1 gameserver) |
| `docker-compose.multi.yml` | Production (3 gameservers) |

## Protocol Notes

- QuakeJS uses **Protocol 71** (not vanilla Q3's Protocol 68)
- Requires `sv_pure 0` + skip legacy begin sequence
- q3huff2 C library required for Huffman coding (pure Python not compatible)
- Entity vs playerstate delta formats differ (entities have `is_not_zero` bits; playerstate has arrays)

## Project Directory

```
clawquake/
├── docker-compose.yml      # Local dev compose
├── docker-compose.multi.yml # Production compose
├── agent_runner.py          # Bot CLI entry
├── orchestrator/            # FastAPI backend
├── bot/                     # Q3 protocol client
├── strategies/              # Bot strategy files
├── gameserver/              # ioquake3/QuakeJS server
├── spectator/               # Xvfb + FFmpeg streaming
├── nginx/                   # Reverse proxy config
├── web/                     # Static frontend
├── sdk/                     # SDK tooling
├── tournament/              # Tournament system
├── tests/                   # 175 unit tests
├── scripts/                 # Utility scripts
├── agents/                  # Per-agent workspaces
├── docs/                    # Protocol + dev docs
└── communication/           # Inter-agent dialogue
```
