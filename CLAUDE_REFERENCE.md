# ClawQuake — Claude Infrastructure Agent Reference Doc

**Last updated**: 2026-02-09 ~12:15am EST (end of session 5)
**Purpose**: Everything Claude (infra agent) knows about the project state, so a fresh session can pick up where we left off.

---

## 1. Project Overview

ClawQuake is an AI bot competition platform built on Quake 3 (QuakeJS). AI agents write strategy files, register bots via API, queue for matches, and the matchmaker automatically pairs them and runs matches on QuakeJS game servers.

- **Repo**: `/Users/johnbest/src/openclaw/clawquake` (GitHub: `jbest2015/clawquake.git`)
- **3-agent workflow**: Claude (infra/orchestration), Codex (API/SDK), Anti-Gravity (game/UI)
- **4 batches completed**: 175/175 tests passing
- **Communication**: Agents coordinate via `communication/dialogue` file (append-only log)
- **Feature backlog**: `FEATURE_TODO.md` in repo root (maintained by Codex)

## 2. Architecture

```
[Browser] --> [nginx :80] --> [orchestrator :8000 (FastAPI)]
                          --> [gameserver-1 :8080/27960 (QuakeJS)]

[orchestrator] --> spawns agent_runner.py subprocesses
              --> each subprocess connects ws://gameserver-1:27960
              --> bot plays game, reports results back
```

### Containers (local docker-compose.yml)
| Container | Image | Ports | Purpose |
|-----------|-------|-------|---------|
| clawquake-server-1 | quakejs (built from `./quakejs`) | 27960/tcp, 8080 | QuakeJS game server |
| clawquake-orchestrator | python:3.12-slim (built from `./orchestrator/Dockerfile`) | 8000 | FastAPI API + matchmaker + process manager |
| clawquake-nginx | nginx:alpine | 80 | Reverse proxy, serves web UI |
| clawquake-spectator | custom (built from `./spectator`) | 8080/tcp (internal) | HLS spectator stream |

### Key Environment Variables (orchestrator)
- `JWT_SECRET` — required, from .env
- `RCON_PASSWORD` — required, from .env
- `INTERNAL_SECRET` — for bot result reporting (default: changeme)
- `MATCH_DURATION` — seconds per match (default: 120)
- `QUEUE_POLL_INTERVAL` — matchmaker poll frequency (default: 5s)
- `GAME_SERVER_HOST` — hostname for game server inside Docker network (set to `gameserver-1`)
- `GAME_SERVER_URLS` — WebSocket URL for bots (set to `ws://gameserver-1:27960`)

## 3. Current State (as of session 5 end — Feb 9 ~12:15am EST)

### What's Working
- **Full matchmaker pipeline**: Queue bots -> matchmaker polls -> creates match -> process_manager spawns agent_runner subprocesses -> bots connect to game server -> play for MATCH_DURATION seconds -> match finalized with winner + ELO
- **Multiple successful matches run locally** including ClaudeMatch1 vs CodexMatch1 (competition_reference vs circlestrafe)
- **All 175 unit tests pass**
- **Dashboard** at http://localhost/ — live dashboard with QuakeJS spectator embed (direct iframe, not HLS)
- **QuakeJS browser client** at http://localhost:8080 for spectating
- **API docs (Swagger)** at http://localhost:8000/docs
- **Spectator stream** — dashboard defaults to direct QuakeJS spectator, HLS available via `?hls=1`
- **Bot spawning** — protocol 71 spawn fix applied (sv_pure 0 + skip legacy begin for protocol 71)

### What's Partially Working
- **`/api/internal/match/report`** returns 422 — payload format mismatch. Match finalization works via process exit detection, so cosmetic but should be fixed.
- **EventStream** (`bot/event_stream.py`) — `_send()` is a no-op (line 54). `_send_sync()` works.
- **`/docs-page` and `/getting-started` routes** — nginx `try_files` catches these and returns the login page. Need explicit `location =` blocks.

### Production Server Status
- **SHUT DOWN** as of this session end. All 5 ClawQuake containers brought down intentionally.
- Needs full redeploy with all recent fixes (matchmaker startup, GAME_SERVER_HOST, protocol 71 spawn fix, streaming fixes, etc.)
- See Section 8 for production server details.

### Uncommitted / Modified Files
```
M  BOT_DEVELOPMENT.md
M  README.md
M  communication/dialogue
M  web/dashboard.html
M  web/docs.html
?? CLAUDE_REFERENCE.md
?? FEATURE_TODO.md
?? STREAM_FIXES_LOG.md
?? results/*.json (match results — many files)
```

### Recent Commits (latest first)
```
b72452e Post final clean-run queue status for Claude/user
1845df1 Fix protocol-71 bot spawn path (pure mode/begin handling)
398963e Log Codex queued on fresh DB for controlled restart
d50d413 Update dialogue: Anti-Gravity paused, 3-player coordination
9256864 Post reset directive for all agents to withdraw queue
a72a24b + 96a2da4 Codex: streaming fixes, dashboard QuakeJS spectator default
```

## 4. Bugs Fixed (All Sessions)

### Bug 1: Matchmaker Never Started (FIXED — session 4)
**File**: `orchestrator/main.py`
**Problem**: `MatchMaker.run_loop()` never launched as asyncio background task.
**Fix**: Added startup/shutdown event handlers with `asyncio.create_task()`.

### Bug 2: Wrong AGENT_RUNNER_PATH (FIXED — session 4)
**File**: `orchestrator/process_manager.py`
**Problem**: `os.path.join(dirname(__file__), "..", "agent_runner.py")` resolved to `/agent_runner.py` in Docker.
**Fix**: Removed `..`, use `os.path.abspath(__file__)`.

### Bug 3: Wrong Game Server Host (FIXED — session 4)
**File**: `docker-compose.yml`
**Problem**: Default `GAME_SERVER_HOST=localhost` doesn't work inside Docker containers.
**Fix**: Set `GAME_SERVER_HOST=gameserver-1` in compose environment.

### Bug 4: Stderr Silently Lost (FIXED — session 4)
**File**: `orchestrator/process_manager.py`
**Problem**: Subprocess stderr was captured but never read/logged.
**Fix**: Added stderr reading and logging on non-zero exit.

### Bug 5: Missing "begin" Command (FIXED — session 1)
**File**: `bot/client.py`
**Problem**: Never sent `begin <serverid>` after gamestate, so server sent empty playerstates.
**Fix**: Added `self.queue_command(f"begin {self.server_id}")` after CA_PRIMED.

### Bug 6: Game Loop Starvation (FIXED — session 1)
**File**: `bot/client.py`
**Problem**: Inner recv loop never timed out, so frames were never sent back to server.
**Fix**: Bounded drain (max 5 packets per frame, 5ms timeout), then send frame.

### Bug 7: Protocol 71 Bot Spawn Regression (FIXED — session 5, by Codex)
**File**: `quakejs/entrypoint.sh` + `bot/client.py`
**Problem**: QuakeJS (protocol 71) was running in pure mode, bot sent legacy begin command.
**Fix**: Set `sv_pure 0` in entrypoint.sh, skip legacy begin for protocol 71 in client.py.

## 5. Key Files Reference

### Orchestrator (FastAPI backend)
| File | Purpose | Key Details |
|------|---------|-------------|
| `orchestrator/main.py` | App entry point | Routes, matchmaker startup, server list loading, WebSocket hub |
| `orchestrator/matchmaker.py` | Match engine | ELO calculator, queue polling, match creation/finalization, `run_loop()` background task |
| `orchestrator/process_manager.py` | Bot subprocess mgmt | Spawns `agent_runner.py` via `subprocess.Popen`, monitors exit codes, enforces timeouts |
| `orchestrator/models.py` | DB models + schemas | SQLAlchemy: UserDB, BotDB, MatchDB, MatchParticipantDB, QueueEntryDB, ApiKeyDB. Pydantic schemas for all. |
| `orchestrator/auth.py` | Authentication | JWT tokens, bcrypt passwords, `get_current_user()`, `get_current_user_or_apikey()` (JWT or X-API-Key) |
| `orchestrator/routes_bots.py` | Bot CRUD | POST/GET /api/bots |
| `orchestrator/routes_keys.py` | API key mgmt | POST/GET/DELETE /api/keys, rotate |
| `orchestrator/routes_queue.py` | Queue mgmt | POST /api/queue/join, GET /api/queue/status, DELETE /api/queue/leave |
| `orchestrator/rcon_pool.py` | Server pool | Multi-server abstraction (not heavily used yet) |
| `orchestrator/websocket_hub.py` | Live events | WebSocket broadcast to dashboard clients |
| `orchestrator/ai_agent_interface.py` | LLM agent API | POST /api/agent/observe, POST /api/agent/act (interactive turn-based) |
| `orchestrator/rate_limiter.py` | Rate limiting | Middleware for API throttling |

### Bot Runtime (runs inside orchestrator container)
| File | Purpose |
|------|---------|
| `agent_runner.py` | CLI entry point: `python agent_runner.py --strategy X --name Y --server ws://... --duration N` |
| `bot/client.py` | Q3 protocol client (WebSocket, Huffman, snapshot parsing) |
| `bot/agent.py` | ClawQuakeAgent wraps client, provides connect/run_background/disconnect |
| `bot/bot.py` | GameView class (players, items, position, health), Q3Bot with callbacks |
| `bot/strategy.py` | StrategyLoader: loads .py strategy files, supports hot-reload |
| `bot/kill_tracker.py` | Q3 kill message parsing (regex-based) |
| `bot/result_reporter.py` | POSTs match results to /api/internal/match/report |
| `bot/event_stream.py` | Emits real-time kill/chat events during match |
| `bot/replay_recorder.py` | Records tick-by-tick game state for replay |

### Strategies
| File | Description |
|------|-------------|
| `strategies/default.py` | Chase nearest player + shoot |
| `strategies/circlestrafe.py` | Orbit target + shoot |
| `strategies/competition_reference.py` | Full competitive: weapon priority, map awareness, retreat |
| `strategies/adaptive_learner.py` | Self-improving: learns opponent patterns, counters |

### Web UI
| File | Route | Purpose |
|------|-------|---------|
| `web/dashboard.html` | `/` | Login + live dashboard with QuakeJS spectator iframe (scores, leaderboard, match history) |
| `web/manage.html` | `/manage.html` | Bot management + API key dashboard |
| `web/spectate.html` | `/spectate.html` | Live spectator page (direct QuakeJS) |
| `web/tournament.html` | `/tournament.html` | Tournament bracket visualization |
| `web/replays.html` | `/replays.html` | Replay viewer with timeline |
| `web/docs.html` | `/docs-page` (**BROKEN** — nginx route) | API documentation |
| `web/getting-started.html` | `/getting-started` (**BROKEN** — nginx route) | Tutorial guide |

### Docker / Deployment
| File | Purpose |
|------|---------|
| `docker-compose.yml` | Local dev: 1 game server + orchestrator + nginx + spectator |
| `docker-compose.multi.yml` | Multi-server: 3 game servers (used on production) |
| `docker-compose.prod.yml` | Production compose variant |
| `orchestrator/Dockerfile` | Builds orchestrator image (python:3.12-slim + bot runtime) |
| `quakejs/Dockerfile` | Builds from `awakenedpower/quakejs-rootless`, adds nginx config |
| `quakejs/entrypoint.sh` | QuakeJS startup — includes `sv_pure 0` fix |
| `nginx/nginx.conf` | Reverse proxy: API, WebSocket, static files |
| `.env` | Secrets: JWT_SECRET, RCON_PASSWORD, INTERNAL_SECRET |

### Documentation
| File | Purpose |
|------|---------|
| `CLAUDE_REFERENCE.md` | This file — Claude agent context |
| `FEATURE_TODO.md` | Feature backlog (maintained by Codex) |
| `STREAM_FIXES_LOG.md` | Codex's streaming fix changelog |
| `PLATFORM_PLAN.md` | Original platform architecture plan |
| `ARCHITECTURE.md` | System architecture doc |
| `DEPLOYMENT.md` | Deployment guide |
| `BOT_DEVELOPMENT.md` | Bot development guide for users |
| `SERVER_CONFIG.md` | Server configuration reference |
| `STATUS.md` | Project status overview |

## 6. API Endpoints Summary

### Auth
- `POST /api/auth/register` — `{username, email, password}` -> `{access_token}`
- `POST /api/auth/login` — `{username, password}` -> `{access_token}`
- `GET /api/auth/me` — current user info

### Keys (require JWT Bearer token)
- `POST /api/keys` — `{name}` -> `{id, key, key_prefix, ...}`
- `GET /api/keys` — list user's keys
- `DELETE /api/keys/{id}` — revoke key
- `POST /api/keys/{id}/rotate` — rotate key

### Bots (require JWT or X-API-Key)
- `POST /api/bots` — `{name}` -> `{id, name, elo, ...}`
- `GET /api/bots` — list user's bots
- `GET /api/bots/{id}` — bot details

### Queue (require JWT or X-API-Key)
- `POST /api/queue/join` — `{bot_id}` -> `{position, status, ...}`
- `GET /api/queue/status` — queue status
- `DELETE /api/queue/leave` — leave queue

### Matches
- `GET /api/matches` — match history (requires auth)
- `GET /api/matches/{id}` — match details (requires auth)

### Internal
- `POST /api/internal/match/report` — bot reports results (X-Internal-Secret header)

### Admin
- `POST /api/admin/match/start` — manually start match
- `GET /api/admin/matches/active` — active match processes
- `GET /api/admin/servers` — server pool status

### Interactive Agent
- `POST /api/agent/observe` — get game state for bot
- `POST /api/agent/act` — send action for bot

### WebSocket
- `/ws/events` — live event stream for dashboard

### Other
- `GET /api/health` — `{status: "ok"}`
- `GET /api/leaderboard` — top 50 bots by ELO
- `GET /api/replays` — list replay files
- `GET /api/replays/{filename}` — serve replay JSON
- `GET /api/status` — live server/match status

## 7. Data Flow: How a Match Runs

1. **User registers** via `/api/auth/register`, gets JWT
2. **Creates API key** via `POST /api/keys` (required for bot ownership validation in matchmaker)
3. **Registers bot** via `POST /api/bots` with name
4. **Joins queue** via `POST /api/queue/join` with bot_id
5. **Matchmaker polls** every `QUEUE_POLL_INTERVAL` seconds in `run_loop()`:
   - Queries QueueEntryDB for `status="waiting"`, ordered by `queued_at`
   - If >= 2 waiting bots, calls `create_match()` -> creates MatchDB + MatchParticipantDB records
6. **Process manager launches bots** via `_run_match_with_processes()`:
   - For each bot: checks owner has active API key (`_owner_has_active_key()`), resolves strategy path (`_get_bot_strategy()`)
   - Calls `process_manager.launch_match()` which spawns `subprocess.Popen("python", "/app/agent_runner.py", ...)`
   - Each subprocess connects to game server via WebSocket, runs strategy for `MATCH_DURATION` seconds
7. **Bots play**: agent_runner loads strategy, connects to QuakeJS, runs tick loop
8. **Match ends**: process_manager detects all subprocesses exited (return_code=0)
9. **Finalization**: matchmaker calls `finalize_match()`:
   - Calculates ELO changes (pairwise FFA formula)
   - Updates BotDB stats (wins, losses, kills, deaths, elo)
   - Sets match winner (highest score)
   - Marks queue entries as "done"

### Server URL Resolution Chain
`_load_server_list()` in main.py:
1. Reads `GAME_SERVERS` env (JSON array) — if set, uses that
2. Fallback: builds from `GAME_SERVER_HOST` (default: "localhost") + `GAME_SERVER_PORT` (default: 27960)
3. `rcon_pool` is initialized with this list
4. `matchmaker._get_server_url()` queries `rcon_pool.get_available_server()` first
5. Fallback: reads `GAME_SERVER_URLS` env, takes first comma-separated value

In Docker, `GAME_SERVER_HOST=gameserver-1` ensures the URL resolves to `ws://gameserver-1:27960`.

## 8. Production Server (Aech)

- **Host**: port.jsbjr.digital (also clawquake.johnbest.ai, IP: 64.111.21.67)
- **SSH (claude user)**: `ssh -o IdentitiesOnly=yes -i /Users/johnbest/.ssh/id_ed25519 claude@port.jsbjr.digital`
- **SSH (jbest2007)**: `ssh -o IdentitiesOnly=yes -i /Users/johnbest/.ssh/JB_aech_priv.cer jbest2007@port.jsbjr.digital`
- **Architecture**: x86_64 (game servers work here, unlike ARM64 Mac)
- **Docker**: v20.10.21, use `docker-compose` (hyphenated) NOT `docker compose`, may need sudo
- **docker-compose version**: v2.20.3
- **Repo location**: `~/clawquake` (under claude user)
- **Compose file used**: `docker-compose.multi.yml` (3 game servers + orchestrator + nginx)
- **Other users on server**: jbest2007 (John Best), jbeck (Jonathan Beck), jlangston (Jake), samclaw, root
- **SSH config note**: SSH config for port.jsbjr.digital references `.ppk` key — always use `-o IdentitiesOnly=yes` to override

### Production Status (as of session 5 end)
- **ALL CLAWQUAKE CONTAINERS ARE DOWN** — intentionally shut down this session
- Previous state was running old code without matchmaker startup fix, GAME_SERVER_HOST fix, or protocol 71 spawn fix
- Needs full redeploy with current main branch

### Production Redeploy Steps
```bash
# 1. Commit & push local changes
cd /Users/johnbest/src/openclaw/clawquake
git add -A && git commit -m "..." && git push

# 2. SSH to server
ssh -o IdentitiesOnly=yes -i /Users/johnbest/.ssh/id_ed25519 claude@port.jsbjr.digital

# 3. Pull latest
cd ~/clawquake && git pull

# 4. Rebuild and start
sudo docker-compose -f docker-compose.multi.yml up -d --build

# 5. Verify
curl -s http://localhost:8000/api/health
sudo docker-compose -f docker-compose.multi.yml logs -f orchestrator
```

### Production HTTPS Note
- Outer `jwilder/nginx-proxy` (nextcloud3-proxy container) handles SSL for all sites
- Returns 500 on `curl -sk https://clawquake.johnbest.ai/api/health` but works in browser
- This is an SSL proxy config issue, not a ClawQuake issue

## 9. Known Issues & Next Steps

### Issues to Fix
1. **`/api/internal/match/report` 422 error** — payload format mismatch between agent_runner's ResultReporter and the endpoint schema. Match finalization works via process exit detection, but per-bot kills/deaths aren't recorded.
2. **`/docs-page` and `/getting-started` nginx routes** — `try_files` catches them. Need `location = /docs-page { ... }` blocks in nginx.conf.
3. **EventStream `_send()` method** has `pass` instead of actual HTTP send at line 54 of `bot/event_stream.py`.
4. **Production redeploy** — containers are down, need commit + push + rebuild with all fixes.

### Feature Backlog (from FEATURE_TODO.md)
1. Human player naming in-game (replace `UnnamedPlayer` with login username)
2. Leaderboard click-through to live telemetry
3. Overhead map with live player dots
4. QuakeJS customization/licensing research

### Potential Improvements
- Reduce MATCH_DURATION for testing (currently 120s, could use 30s)
- Add proper bot result collection (fix the 422 so kills/deaths are recorded)
- Strategy resolution: `_get_bot_strategy()` looks for `strategies/<bot_name>.py` — could add `strategy_path` column to BotDB
- Production HTTPS: investigate jwilder/nginx-proxy 500 error on external curl

## 10. Testing

### Running Tests
```bash
cd /Users/johnbest/src/openclaw/clawquake
pytest tests/ -v  # All 175 tests
```

### Test Files (22 total)
- `tests/test_api.py` (13) — Codex: auth, keys, bots, queue
- `tests/test_kill_tracker.py` (10) — Anti-Gravity: Q3 kill parsing
- `tests/test_matchmaker.py` (13) — Claude: ELO, queue, match lifecycle
- `tests/test_rcon.py` (11) — Claude: RCON pool
- `tests/test_result_reporter.py` (3) — Anti-Gravity: match reporting
- `tests/test_strategy.py` (4) — Anti-Gravity: strategy system
- `tests/test_integration_matchmaker.py` (18) — Claude: process manager + full lifecycle
- `tests/test_websocket.py` (3) — Codex: WebSocket hub
- `tests/test_e2e.py` (27) — Claude: end-to-end API flows
- `tests/test_rate_limiter.py` (12) — Claude: rate limiting
- `tests/test_key_rotation.py` (13) — Claude: API key rotation/expiry
- `tests/test_sdk.py` (14) — Codex: SDK unit tests
- `tests/test_sdk_errors.py` (8) — Codex: SDK error handling
- `tests/test_matchmaker_expiry.py` (2) — Codex: key expiry in matchmaker
- `tests/test_bracket.py` (10) — Anti-Gravity: tournament brackets
- `tests/test_adaptive.py` (6) — Anti-Gravity: adaptive learner
- `tests/test_replay.py` (6) — Anti-Gravity: replay system
- `tests/test_adaptive_db.py` (2) — Anti-Gravity: adaptive learner DB
- `tests/test_agent_interface.py` (4) — Anti-Gravity: interactive agent API

### Quick Local Match Test
```bash
# Start containers
docker compose up -d --build

# Register + login
REG=$(curl -s -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"test","email":"t@t.com","password":"pass123"}')
TOKEN=$(echo "$REG" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Create API key (REQUIRED — matchmaker checks owner has active key)
KEY=$(curl -s -X POST http://localhost:8000/api/keys \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"name":"k"}')
API_KEY=$(echo "$KEY" | python3 -c "import sys,json; print(json.load(sys.stdin)['key'])")

# Register 2 bots
B1=$(curl -s -X POST http://localhost:8000/api/bots \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" -d '{"name":"Bot1","strategy":"competition_reference"}')
B1_ID=$(echo "$B1" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

B2=$(curl -s -X POST http://localhost:8000/api/bots \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" -d '{"name":"Bot2","strategy":"circlestrafe"}')
B2_ID=$(echo "$B2" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Queue both — matchmaker picks them up within 5 seconds
curl -s -X POST http://localhost:8000/api/queue/join \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" -d "{\"bot_id\": $B1_ID}"
curl -s -X POST http://localhost:8000/api/queue/join \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" -d "{\"bot_id\": $B2_ID}"

# Watch logs for match creation + bot launch
docker logs -f clawquake-orchestrator
```

## 11. Session History (Major Milestones)

1. **Session 1** (Feb 8 ~1:30am): Built bot framework, strategy system, discovered Q3 protocol bugs (missing `begin` command, game loop starvation), fixed them, got **first AI kill in Quake**.
2. **Session 2** (Feb 8 afternoon): Platform build Batches 1-4 across 3 agents in parallel — matchmaker, API layer, game intelligence, SDK, tournament brackets, replay system, interactive agent interface. 175/175 tests.
3. **Session 3**: Production deployment — switched game servers from OpenArena to QuakeJS, deployed to Hetzner server.
4. **Session 4** (Feb 8 ~9:30pm): Fixed matchmaker startup, AGENT_RUNNER_PATH, GAME_SERVER_HOST. Ran successful end-to-end match locally (AlphaBot vs BetaBot, return_code=0, winner determined, ELO calculated).
5. **Session 5** (Feb 9 ~12:00am): Codex fixed streaming (dashboard defaults to direct QuakeJS spectator iframe, HLS opt-in). Codex fixed protocol 71 bot spawn regression (sv_pure 0 + skip legacy begin). Ran multiple live matches (ClaudeMatch1 vs CodexMatch1). **Production shut down** intentionally for clean redeploy. Codex added FEATURE_TODO.md with backlog. Anti-Gravity offline for latter half of session.

## 12. Lessons Learned

1. **`os.path.dirname(__file__)` + `..` is fragile in Docker** — when files are copied flat into `/app/`, going up one level goes to `/` which is wrong. Use `os.path.abspath(__file__)` and avoid `..`.
2. **Python exit code 2 = "can't open file"** — if `subprocess.Popen(["python", "/nonexistent.py"])` runs, Python itself returns 2, not FileNotFoundError.
3. **Always log subprocess stderr** — without it, exit code 2 was a complete mystery.
4. **Docker networking: `localhost` != `service-name`** — inside a container, `localhost` is that container. Other containers are reached by service name (`gameserver-1`).
5. **Matchmaker needs explicit startup** — FastAPI doesn't auto-start background tasks. Need `@app.on_event("startup")` with `asyncio.create_task()`.
6. **nginx `try_files $uri $uri/ /index.html`** catches friendly URLs — need explicit `location =` blocks for route aliases like `/docs-page`.
7. **FastAPI bare params are query params, not JSON body** — `def observe(bot_id: int)` expects `?bot_id=1`, not `{"bot_id": 1}`.
8. **OpenArena game servers crash on ARM64 Mac** (QVM incompatibility) — only work on x86_64.
9. **API key is required for matchmaker** — `_owner_has_active_key()` check means bots won't launch without at least one active, non-expired API key for the owner.
10. **Bot name uniqueness is global** — BotDB has `unique=True` on name column. Can't reuse names across users.
11. **Protocol 71 (QuakeJS) vs Protocol 68 (vanilla Q3)** — QuakeJS uses protocol 71. Must set `sv_pure 0` and skip legacy begin command for protocol 71 servers. Otherwise bots connect but never spawn.
12. **Fresh DB on volume wipe** — `docker compose down -v` wipes the SQLite volume. All users/bots/matches reset. Must re-register everything.
13. **Production Docker uses `docker-compose` (hyphenated)** — older Docker version (20.10.21) on Aech doesn't support `docker compose` (space). Always use `docker-compose` and may need `sudo`.
