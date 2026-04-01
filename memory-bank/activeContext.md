# Active Context: ClawQuake

## Current Focus

- Production redeployment — containers are down, need to push all accumulated fixes
- Fix hanging test suite (pytest doesn't complete)
- Begin feature work from backlog

## Recent Changes (as of March 2026)

- Fixed matchmaker startup (missing asyncio task)
- Fixed Docker AGENT_RUNNER_PATH resolution
- Fixed inter-container networking (service names not localhost)
- Fixed Protocol 71 spawn sequence (sv_pure 0 + skip legacy begin)
- Fixed strategy loader and subprocess logging
- Fixed entity crash bugs
- Fixed EventStream._send() no-op (commit 0b70cc2)
- Fixed nginx routes for /docs-page and /getting-started (commit 2890c30)
- Fixed zero-damage hit registration (commit 26975ac)
- Implemented native lead aiming and velocity prediction (commit d9795f8)
- Updated CLAUDE.md with undocumented components and gotchas (PR #1)
- All 175+ unit tests passing

## Next Steps

- Redeploy production with all accumulated fixes
- Fix hanging test suite
- Fix match report 422 (cosmetic)
- Begin feature work from backlog (player naming, leaderboard telemetry, overhead map)

## Active Decisions

- 3-agent dev model (Claude/Codex/Anti-Gravity) with specialized roles
- Strategy files loaded from disk (MCP transport not yet integrated)
- SQLite for now (no need for Postgres at current scale)
- Protocol 71 (QuakeJS) is the target — vanilla Q3 Protocol 68 not supported
