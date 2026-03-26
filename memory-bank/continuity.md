# Continuity: ClawQuake

## Last Session: 2025-02-09 (Session 5+6)

- Fixed strategy loader, subprocess logging, entity crashes
- Added debug instrumentation throughout
- All 175 unit tests passing
- Production containers still down

## Handoff for Next Session

Priority: redeploy production with all accumulated fixes. The local stack is solid — production just needs to be brought up to date.

## Context Preservation Strategy

- Claude Code memory files at `~/.claude/projects/.../memory/`
- Obsidian vault memory bank (this directory)
- Inter-agent dialogue at `communication/dialogue` in repo
- Status tracked in `STATUS.md` and `FEATURE_TODO.md` in repo

## Current State

All core systems functional locally: matchmaker, bot spawning, Protocol 71 connection, dashboard, spectator. Production is down and needs redeployment. There are uncommitted files (dashboard.html, spectate.html, entrypoint.sh, CLAUDE_REFERENCE.md, results/*.json) that should be committed.

## Key Context for Next Session

1. Production SSH: `ssh -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519 claude@port.jsbjr.digital`
2. Production Docker uses `docker-compose` (hyphenated), may need `sudo`
3. Use service names (not localhost) between Docker containers
4. Protocol 71 requires `sv_pure 0` + skip legacy begin
5. API keys are required for matchmaker bot launching

## Knowledge Transfer Notes

- The q3huff2 C library is essential — pure Python Huffman is NOT compatible with QuakeJS
- Entity and playerstate delta formats differ (entities have `is_not_zero` bits; playerstate has arrays)
- Bot `game.my_position` was historically stale — verify snapshot parsing feeds GameView correctly
- Match finalization works via process exit, not the `/api/internal/match/report` endpoint (which returns 422)
