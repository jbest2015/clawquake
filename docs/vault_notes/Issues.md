# Issues: ClawQuake

## Known Bugs

- [ ] `/api/internal/match/report` returns 422 — cosmetic, finalization works via process exit
- [x] `/docs-page` and `/getting-started` nginx routes — fixed (commit 2890c30)
- [x] `EventStream._send()` no-op — fixed (commit 0b70cc2)
- [ ] Production HTTPS: `jwilder/nginx-proxy` returns 500 on curl
- [ ] Production containers down — needs redeploy with all accumulated fixes

## Bugs Fixed (Sessions 1-5)

- [x] Matchmaker never started — missing asyncio startup task
- [x] Wrong `AGENT_RUNNER_PATH` in Docker — `os.path ..` resolves wrong
- [x] `GAME_SERVER_HOST=localhost` fails in Docker — must use service name
- [x] Protocol 71 spawn — need `sv_pure 0` + skip legacy begin
- [x] Segfault in q3huff2 C extension — buffer overflow from missing `bits_remaining` tracking
- [x] Gamestate not loading — signed sequence read, missing snap_flags/area_mask, wrong entity delta format
- [x] Fragment reassembly broken — signed sequence read
- [x] Entity delta parse errors — complete rewrite of snapshot.py needed

## Feature Requests

See [[memory-bank/tasks|Tasks]] for the full backlog, or `FEATURE_TODO.md` in repo.

1. Human player naming (replace UnnamedPlayer)
2. Leaderboard click-through to live telemetry
3. Overhead map with live player dots
4. QuakeJS/Quake code customization research
5. MCP strategy library/runtime integration
6. Session persistence across browser refresh
7. Spectator mode selection (follow bot or free-float)
8. Crypto betting on bot matches (exploratory)
