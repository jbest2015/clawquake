# Active Context: ClawQuake

## Current Focus

- Production redeployment — containers are down, need to push all accumulated fixes
- Uncommitted files need to be committed: dashboard.html, spectate.html, entrypoint.sh, CLAUDE_REFERENCE.md, results/*.json

## Recent Changes (as of Session 5, Feb 9 2025)

- Fixed matchmaker startup (missing asyncio task)
- Fixed Docker AGENT_RUNNER_PATH resolution
- Fixed inter-container networking (service names not localhost)
- Fixed Protocol 71 spawn sequence (sv_pure 0 + skip legacy begin)
- Added debug instrumentation throughout
- Fixed strategy loader and subprocess logging
- Fixed entity crash bugs
- All 175 unit tests passing

## Next Steps

- Redeploy production with all accumulated fixes
- Commit outstanding uncommitted files
- Fix remaining known bugs (422 on match report, nginx route issues, EventStream no-op)
- Begin feature work from backlog (player naming, leaderboard telemetry, overhead map)

## Active Decisions

- 3-agent dev model (Claude/Codex/Anti-Gravity) with specialized roles
- Strategy files loaded from disk (MCP transport not yet integrated)
- SQLite for now (no need for Postgres at current scale)
- Protocol 71 (QuakeJS) is the target — vanilla Q3 Protocol 68 not supported
