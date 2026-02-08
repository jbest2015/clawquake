# ClawQuake Platform — Work Packages & Implementation Plan

## Pre-Flight: Security Fix (BEFORE ANY CODING)

**4 hardcoded secrets found in the public repo — must fix immediately:**

| File | Line | Secret | Fix |
|------|------|--------|-----|
| `docker-compose.yml` | 29 | `JWT_SECRET=clawquake-prod-secret-change-me` | Move to `.env` file |
| `orchestrator/auth.py` | 13 | `"clawquake-dev-secret-change-in-prod"` | Remove default, require env var |
| `orchestrator/rcon.py` | 9 | `"clawquake_rcon_2026"` | Remove default, require env var |
| `gameserver/server.cfg` | 10 | `set rconPassword "clawquake_rcon_2026"` | Template from env var |

**Action:** Create `.env.example` (no real values), add `.env` to `.gitignore`, update code to require env vars with no fallback defaults. Rotate all secrets on the server.

---

## Vision

Users register on the website, get an API key, give it to their AI agent. The AI registers a bot, writes strategy code, joins the queue, plays 2-minute rounds, reviews results, iterates. Users watch through their bot's eyes via QuakeJS spectator. Continuous ranked queue with ELO.

## Architecture

```
clawquake.johnbest.ai (single domain)
         |
    [nginx proxy]
   /    |      |      \
  /   /api/*  /server/N  /spectate/N
 |      |        |            |
[Web] [Orchestrator] [QuakeJS   [QuakeJS browser
 UI]   FastAPI +      servers]   spectator]
       matchmaker     :27961+N
         |
     [SQLite DB]
```

---

## Shared Interfaces (All agents code against these)

### New Database Models (added to `orchestrator/models.py`)

```python
# Claude adds these:
class QueueEntryDB(Base):
    __tablename__ = "queue"
    id, bot_id (FK bots.id), user_id (FK users.id), queued_at, status (waiting|matched|playing|done)

class MatchParticipantDB(Base):
    __tablename__ = "match_participants"
    id, match_id (FK matches.id), bot_id (FK bots.id), kills, deaths, score, elo_before, elo_after

# Codex adds these:
class ApiKeyDB(Base):
    __tablename__ = "api_keys"
    id, key_hash (SHA-256), key_prefix (first 8 chars), user_id (FK users.id), name, created_at, last_used, is_active
```

### New API Endpoints

```
# Keys (Codex builds, auth via JWT)
POST   /api/keys              -> {key, key_prefix, name}   # Create API key (full key shown once)
GET    /api/keys              -> [{key_prefix, name, ...}]  # List my keys
DELETE /api/keys/{key_id}     -> {deleted: true}            # Revoke key

# Bots (Codex builds, auth via JWT or X-API-Key)
POST   /api/bots              -> BotResponse               # Register bot
GET    /api/bots              -> [BotResponse]              # List my bots
GET    /api/bots/{bot_id}     -> BotResponse                # Bot details

# Queue (Codex builds endpoints, Claude builds matchmaker logic)
POST   /api/queue/join        -> QueueStatus                # Join queue
GET    /api/queue/status      -> QueueStatus                # Check position
DELETE /api/queue/leave       -> {left: true}               # Leave queue

# Match reporting (Claude builds, Anti-Gravity integrates from agent_runner)
POST   /api/internal/match/report  -> {ok: true}            # Bot posts results (internal secret auth)
GET    /api/matches/{id}           -> MatchResult            # Match details with participants
```

### Auth: API Key Support (Codex adds to `orchestrator/auth.py`)

```python
def get_current_user_or_apikey(credentials, api_key=Header(None, alias="X-API-Key"), db) -> UserDB:
    """Accept either Bearer JWT or X-API-Key header."""
```

---

## BATCH 1: Foundation (All 3 agents work in parallel)

### CLAUDE: Matchmaker Engine + RCON Pool + Test Infrastructure

**What:** Build the core matchmaking engine that pairs bots from the queue, creates matches, calculates ELO. Multi-server RCON abstraction. Shared test fixtures.

**CREATE:**

| File | Key Contents |
|------|-------------|
| `orchestrator/matchmaker.py` (~250 lines) | `EloCalculator.calculate(winner_elo, loser_elo, k=32)`, `MatchMaker` class with `poll_queue()`, `create_match(bot_ids, map)`, `collect_results(match_id, results)`, `finalize_match(match_id)` (ELO calc + DB update), `run_loop()` (background task). Constants: `MATCH_DURATION=120`, `QUEUE_POLL_INTERVAL=5`, `MIN_PLAYERS=2`, `MAX_PLAYERS=4` |
| `orchestrator/rcon_pool.py` (~100 lines) | `RconPool` class: `__init__(servers: list[dict])`, `get_available_server()`, `mark_busy/free(server_id)`, `send_rcon(server_id, cmd)`, `get_status(server_id)` |
| `tests/__init__.py` | Empty |
| `tests/conftest.py` (~80 lines) | Shared pytest fixtures: `db` (in-memory SQLite), `client` (FastAPI TestClient), `mock_rcon` |
| `tests/test_matchmaker.py` (~200 lines) | Tests below |
| `tests/test_rcon.py` (~80 lines) | Tests below |

**MODIFY:**

| File | Changes |
|------|---------|
| `orchestrator/models.py` | Add `QueueEntryDB`, `MatchParticipantDB` models + Pydantic schemas `QueueStatus`, `MatchResult` |
| `orchestrator/main.py` | Add lifespan startup for matchmaker background task. Add `POST /api/internal/match/report` endpoint (secret-authenticated). Add `GET /api/matches/{match_id}` with participant details. |

**Tests:**
```
tests/test_matchmaker.py:
  test_elo_calculation_winner_gains
  test_elo_calculation_symmetric (total ELO conserved)
  test_elo_calculation_upset (bigger swing for underdog)
  test_queue_poll_no_bots (empty queue = no-op)
  test_queue_poll_one_bot (stays waiting)
  test_queue_poll_two_bots_creates_match
  test_create_match_db_record
  test_finalize_match_updates_elo
  test_finalize_match_updates_bot_stats

tests/test_rcon.py:
  test_parse_status_response (real captured data)
  test_parse_status_empty
  test_rcon_pool_get_available
  test_rcon_pool_mark_busy_free
```

**Stopping point:** Matchmaker can take bots from queue, create matches, calculate ELO — all verified by unit tests. RCON pool manages multiple servers. Test infrastructure ready for other agents.

**Done signal → dialogue:**
```
[TS] Claude: Batch 1 complete. Matchmaker engine + RCON pool + test infra ready.
Created: orchestrator/matchmaker.py, orchestrator/rcon_pool.py, tests/conftest.py, tests/test_matchmaker.py, tests/test_rcon.py
Modified: orchestrator/models.py, orchestrator/main.py
Run: pytest tests/test_matchmaker.py tests/test_rcon.py -v
```

---

### CODEX: API Layer — Bot Registration, API Keys, Queue Endpoints, Dashboard

**What:** User-facing API for bot management, API key auth, queue endpoints. Web dashboard updates for bot management.

**CREATE:**

| File | Key Contents |
|------|-------------|
| `orchestrator/api_keys.py` (~120 lines) | `generate_api_key()` -> `"cq_" + 40 hex`, `hash_api_key(key)` -> SHA-256, `verify_api_key(key, hash)`, `get_user_by_api_key(key, db)` |
| `orchestrator/routes_bots.py` (~150 lines) | APIRouter `/api/bots`. `POST /` register bot (unique name, owned by user). `GET /` list my bots. `GET /{bot_id}` bot details. |
| `orchestrator/routes_keys.py` (~100 lines) | APIRouter `/api/keys`. `POST /` create key (returns full key once). `GET /` list keys (prefix only). `DELETE /{key_id}` revoke. |
| `orchestrator/routes_queue.py` (~120 lines) | APIRouter `/api/queue`. `POST /join` join queue. `GET /status` position. `DELETE /leave` leave. |
| `web/manage.html` (~200 lines) | Bot management page: register bots, view API keys, join queue, copy-to-clipboard for keys. |
| `tests/test_api.py` (~250 lines) | Tests below |

**MODIFY:**

| File | Changes |
|------|---------|
| `orchestrator/models.py` | Add `ApiKeyDB` model + Pydantic schemas `ApiKeyCreate`, `ApiKeyResponse`, `ApiKeyCreated`, `BotRegister` |
| `orchestrator/auth.py` | Add `get_current_user_or_apikey()` that accepts Bearer JWT OR X-API-Key header |
| `orchestrator/main.py` | Include 3 new routers. Serve manage.html. |
| `web/dashboard.html` | Add "Manage Bots" link/tab. Queue status indicator. |
| `orchestrator/requirements.txt` | Add `httpx`, `pytest`, `pytest-asyncio` |

**Tests:**
```
tests/test_api.py:
  test_register_user
  test_login_user
  test_create_api_key
  test_list_api_keys (shows prefix, not full key)
  test_delete_api_key (revoke works)
  test_auth_with_api_key (X-API-Key header works)
  test_register_bot
  test_register_bot_duplicate_name (400)
  test_list_bots (own bots only)
  test_join_queue
  test_join_queue_not_own_bot (403)
  test_leave_queue
  test_queue_status
```

**Stopping point:** All API endpoints work with TestClient. API key auth works. Bot registration works. Queue endpoints work. Dashboard links to manage page.

**Done signal → dialogue:**
```
[TS] Codex: Batch 1 complete. API layer ready.
Created: orchestrator/api_keys.py, routes_bots.py, routes_keys.py, routes_queue.py, web/manage.html, tests/test_api.py
Modified: models.py, auth.py, main.py, requirements.txt, dashboard.html
Run: pytest tests/test_api.py -v
```

---

### ANTI-GRAVITY: Game Layer — Kill Tracker, Result Reporter, Reference Strategy

**What:** Reliable kill/death tracking extracted to its own module. Result reporting from agent_runner back to orchestrator. Competition-grade reference strategy.

**CREATE:**

| File | Key Contents |
|------|-------------|
| `bot/kill_tracker.py` (~150 lines) | `KillTracker` class: `parse_server_command(text)` handles ALL Q3 kill formats ("was railgunned by", "almost dodged", "killed by", color codes `^[0-9]`). `record(killer, victim, weapon)`. Properties: `kills`, `deaths`, `kd_ratio`. `to_dict()`. |
| `bot/result_reporter.py` (~100 lines) | `ResultReporter` class: `__init__(orchestrator_url, internal_secret)`. `async report_match(match_id, bot_id, bot_name, kills, deaths, duration, strategy_name, strategy_version)` -> POSTs to `/api/internal/match/report`. Handles connection errors gracefully. |
| `strategies/competition_reference.py` (~200 lines) | Reference strategy: item awareness (health/armor pickups), map boundary awareness, weapon priority (RL>LG>RG>PG>SG>MG), engagement ranges per weapon, health-based retreat. Shows best practices. |
| `tests/test_kill_tracker.py` (~150 lines) | Tests below |
| `tests/test_result_reporter.py` (~80 lines) | Tests below |
| `tests/test_strategy.py` (~100 lines) | Tests below |

**MODIFY:**

| File | Changes |
|------|---------|
| `agent_runner.py` | Add `--match-id`, `--bot-id`, `--orchestrator-url`, `--internal-secret` CLI args. On exit, POST results via `ResultReporter` if orchestrator-url provided. Use `KillTracker` instead of inline parsing. **Backward compatible** — works without new flags. |
| `bot/bot.py` | Import `KillTracker`, delegate `_parse_kill_message` to it. `on_kill` callback unchanged. |

**Tests:**
```
tests/test_kill_tracker.py:
  test_parse_was_railgunned_by
  test_parse_was_melted_by
  test_parse_almost_dodged
  test_parse_killed_by
  test_parse_falling (suicide, no killer)
  test_parse_with_color_codes (^1, ^2, etc.)
  test_record_kill_increments
  test_record_death_increments
  test_kd_ratio_zero_deaths (no div/0)
  test_to_dict

tests/test_result_reporter.py:
  test_report_match_success (mock HTTP, verify POST body)
  test_report_match_connection_error (graceful handling)
  test_report_from_tracker

tests/test_strategy.py:
  test_strategy_loader_loads_file
  test_strategy_tick_returns_actions
  test_strategy_context_persistence
  test_strategy_hot_reload
  test_default_strategy_runs
  test_competition_reference_runs
```

**Stopping point:** Kill tracker reliably parses all Q3 kill formats. Result reporter POSTs to orchestrator. Competition reference strategy works. Agent runner backward compatible.

**Done signal → dialogue:**
```
[TS] Anti-Gravity: Batch 1 complete. Game layer ready.
Created: bot/kill_tracker.py, bot/result_reporter.py, strategies/competition_reference.py, tests/test_kill_tracker.py, tests/test_result_reporter.py, tests/test_strategy.py
Modified: agent_runner.py, bot/bot.py
Run: pytest tests/test_kill_tracker.py tests/test_result_reporter.py tests/test_strategy.py -v
```

---

## BATCH 1 MERGE GATE

**Trigger:** All 3 agents post "Batch 1 complete" to dialogue.

**Merge order:** Claude first (models.py + matchmaker) → Codex (models.py additions + routes) → Anti-Gravity (bot changes + tests)

**Conflict risk:** Both Claude and Codex modify `orchestrator/models.py` — both are APPEND-ONLY (adding new models), so merge should be clean.

**Shared test run:**
```bash
cd /Users/johnbest/src/openclaw/clawquake
pip install pytest pytest-asyncio httpx
pytest tests/ -v
```

**Pass criteria:** ALL tests pass. No import errors. Existing auth endpoints still work.

---

## BATCH 2: Integration (After Batch 1 merge)

### CLAUDE: Process Manager + Docker Multi-Server

**What:** Wire matchmaker to actually launch agent_runner subprocesses. Multi-server docker-compose.

**CREATE:**

| File | Key Contents |
|------|-------------|
| `orchestrator/process_manager.py` (~150 lines) | `BotProcessManager`: `launch_bot(match_id, bot_id, bot_name, strategy_path, server_url, duration)` spawns agent_runner subprocess. `wait_for_match(match_id, processes)` waits for completion. `kill_match(match_id)` force-kill. `active_matches()` status. |
| `docker-compose.multi.yml` (~60 lines) | Multiple gameserver instances (gameserver-1, gameserver-2), orchestrator with server list env vars |
| `tests/test_integration_matchmaker.py` (~150 lines) | `test_full_match_lifecycle`, `test_match_timeout`, `test_concurrent_matches`, `test_elo_updates_after_match` |

**MODIFY:** `orchestrator/matchmaker.py` (wire to ProcessManager), `orchestrator/main.py` (server list from env)

---

### CODEX: WebSocket Live Updates + Spectator Page

**What:** Real-time dashboard via WebSocket. QuakeJS spectator page.

**CREATE:**

| File | Key Contents |
|------|-------------|
| `orchestrator/websocket_hub.py` (~120 lines) | `WebSocketHub`: `connect()`, `disconnect()`, `broadcast(event_type, data)`. Events: match_started, match_ended, queue_update, kill_event. |
| `web/spectate.html` (~150 lines) | QuakeJS embed for spectating, match info overlay, auto-follow match |
| `tests/test_websocket.py` (~80 lines) | `test_connect`, `test_broadcast`, `test_disconnect` |

**MODIFY:** `orchestrator/main.py` (WebSocket endpoint `/ws/events`), `web/dashboard.html` (replace polling with WebSocket), `nginx/nginx.conf` (WebSocket proxy + spectator routes)

---

### ANTI-GRAVITY: Game Intelligence Utilities

**What:** Item classification, spatial awareness, combat analysis — enriched GameView.

**CREATE:**

| File | Key Contents |
|------|-------------|
| `bot/game_intelligence.py` (~200 lines) | `ItemClassifier.classify_entity()`, `SpatialAwareness` (falling, stuck detection), `CombatAnalyzer` (weapon selection, position prediction, engage decision) |
| `bot/event_stream.py` (~80 lines) | `EventStream`: emit kills/scores/status to orchestrator in real-time during matches |
| `tests/test_game_intelligence.py` (~150 lines) | Item classification, spatial detection, weapon selection, position prediction tests |
| `tests/test_event_stream.py` (~60 lines) | Emit tests with mock HTTP |

**MODIFY:** `bot/bot.py` (add `GameView.items`, `.am_i_falling`, `.best_weapon`), `agent_runner.py` (create EventStream if orchestrator-url set), `strategies/competition_reference.py` (use new GameView features)

---

## BATCH 2 MERGE GATE

**Merge order:** Claude → Codex → Anti-Gravity

**Test:** `pytest tests/ -v`

**Smoke test:** `docker-compose up -d`, register user, create API key, register bot, join queue, verify match starts.

---

## BATCH 3: Polish (After Batch 2 merge)

| Agent | Work |
|-------|------|
| **Claude** | E2E test suite (`tests/test_e2e.py`), rate limiter, API key rotation/expiry |
| **Codex** | Python SDK (`sdk/clawquake_sdk.py`), API docs page (`web/docs.html`), getting-started guide |
| **Anti-Gravity** | Tournament bracket system (`tournament/`), adaptive learner strategy, replay recording |

---

## Communication Protocol

All agents post to `communication/dialogue`. Format: `[ISO-TIMESTAMP] Agent: message`

Required posts:
- **Starting:** `[TS] Agent: Starting Batch N. Working on: <summary>`
- **Blocked:** `[TS] Agent: BLOCKED on <issue>. Need <what> from <who>.`
- **Done:** `[TS] Agent: Batch N complete. <files>. All tests pass.`
- **Merge conflict:** `[TS] Agent: Merge conflict in <file>. Resolution: <approach>.`

## Test Configuration

```ini
# pyproject.toml or pytest.ini
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

All tests use shared fixtures from `tests/conftest.py` (Claude creates in Batch 1).

---

## Verification (End-to-End)

1. User registers on website → gets JWT
2. Creates API key → gets `cq_xxxx...`
3. AI uses API key to register bot → bot appears on dashboard
4. Bot joins queue → position shown
5. 2+ bots queued → matchmaker creates match, launches bots
6. 2-minute round plays → results POSTed to orchestrator
7. ELO updated → leaderboard reflects new rankings
8. User clicks "Watch" → sees QuakeJS spectator view
9. Match history shows results with participant stats
