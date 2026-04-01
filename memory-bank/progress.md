# Progress: ClawQuake

## What Works

- FastAPI orchestrator (auth, status, leaderboard, match history, API keys)
- JWT + API Key dual authentication
- ELO matchmaker (async polling, bot pairing, match lifecycle)
- Bot spawning via subprocess (process_manager)
- Q3 Protocol 71 client (WebSocket, Huffman, fragment reassembly, delta compression)
- Gamestate parsing (config strings, entity baselines, snapshots)
- Strategy hot-reload system (auto-reloads every 5s)
- Dashboard web UI (login, leaderboard, live match status)
- Spectator mode (QuakeJS in-browser)
- Tournament bracket system
- 175+ unit tests — all passing
- Docker Compose local and production configurations
- Inter-agent communication channel (dialogue file)
- EventStream real-time event emission (fixed commit 0b70cc2)
- nginx routes for /docs-page and /getting-started (fixed commit 2890c30)
- Native lead aiming and velocity prediction for bots (commit d9795f8)
- Hit registration via clc_move (fixed commit 26975ac)

## What's Left to Build

- Production redeployment with all fixes
- MCP strategy library/runtime integration
- Human player naming (replace UnnamedPlayer)
- Leaderboard click-through telemetry
- Overhead map with live player dots
- Session persistence across browser refresh
- Spectator mode selection (follow bot or free-float)
- Improved bot movement/navigation (still walk off edges)

## Known Issues

- `/api/internal/match/report` returns 422 (cosmetic — finalization works via process exit)
- Production HTTPS: jwilder/nginx-proxy returns 500
- Production containers currently DOWN
- Test suite may hang (needs investigation)

## Milestones

- [x] Bot connects to QuakeJS server (Protocol 71)
- [x] Full gamestate + snapshot parsing
- [x] Matchmaker pairs and launches bots
- [x] Dashboard with leaderboard and live status
- [x] Strategy hot-reload working
- [x] 175 unit tests passing
- [ ] Production stable and live
- [ ] MCP strategy transport integrated
- [ ] Spectator mode with bot-follow/free-float selection
