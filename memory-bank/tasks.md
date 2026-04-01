# Tasks: ClawQuake

## Current Tasks (Active)

- [ ] Redeploy production with all accumulated fixes (containers currently DOWN)
- [ ] Fix `/api/internal/match/report` 422 response
- [ ] Investigate and fix hanging test suite

## Future Tasks (Backlog)

- [ ] Human player naming in-game (replace UnnamedPlayer)
- [ ] Leaderboard click-through to live telemetry
- [ ] Overhead map with live player dots
- [ ] QuakeJS/Quake code customization research
- [ ] MCP strategy library/runtime integration
- [ ] Session persistence across browser refresh
- [ ] Spectator mode selection (follow bot or free-float)
- [ ] Crypto betting / wagering on bot matches (exploratory)
- [ ] Fix production HTTPS (jwilder/nginx-proxy returns 500)
- [ ] Improve bot navigation (reduce falling off edges)

## Completed Tasks

- [x] FastAPI orchestrator with auth, status, leaderboard
- [x] JWT + API Key dual authentication
- [x] ELO matchmaker (async polling, pairing, lifecycle)
- [x] Bot subprocess spawning (process_manager)
- [x] Q3 Protocol 71 client (WebSocket, Huffman, fragments, deltas)
- [x] Gamestate + snapshot parsing
- [x] Strategy hot-reload system
- [x] Dashboard web UI
- [x] Spectator mode (QuakeJS in-browser)
- [x] Tournament bracket system
- [x] 175 unit tests
- [x] Docker Compose configs (local + production)
- [x] Fix matchmaker startup (missing asyncio task)
- [x] Fix AGENT_RUNNER_PATH in Docker
- [x] Fix inter-container networking (service names)
- [x] Fix Protocol 71 spawn (sv_pure 0 + skip legacy begin)
- [x] Fix q3huff2 segfault (buffer overflow)
- [x] Fix gamestate loading (signed sequence, snap_flags, entity deltas)
- [x] Fix fragment reassembly
- [x] Rewrite snapshot.py for correct delta formats
- [x] Fix nginx routes for `/docs-page` and `/getting-started` (commit 2890c30)
- [x] Fix `EventStream._send()` no-op (commit 0b70cc2)
- [x] Fix zero-damage hit registration (commit 26975ac)
- [x] Implement native lead aiming and velocity prediction (commit d9795f8)
- [x] Update CLAUDE.md with undocumented components and gotchas (PR #1)
- [x] Commit all uncommitted files
