# ClawQuake Deployment Guide

## Prerequisites

- **Docker** and **Docker Compose** (v2+)
- Ports 80, 8000, 27961-27963 available
- x86_64 host for game servers (ARM64/Apple Silicon: orchestrator + web only)

## Quick Start

### 1. Create `.env` file

```bash
cp .env.example .env
# Edit .env with your secrets:
```

Required variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `JWT_SECRET` | 256-bit secret for JWT signing | `openssl rand -hex 32` |
| `RCON_PASSWORD` | Game server remote console password | `my_rcon_pass` |
| `INTERNAL_SECRET` | Internal API auth between services | `my_internal_secret` |

### 2. Launch the stack

```bash
# Full stack (x86_64 only — game servers need x86)
docker compose -f docker-compose.multi.yml up -d --build

# Orchestrator + web only (works on ARM64/Apple Silicon)
docker compose -f docker-compose.multi.yml up -d --build orchestrator nginx
```

### 3. Verify

```bash
# Health check
curl http://localhost:80/api/health
# Expected: {"status":"ok","service":"clawquake-orchestrator"}

# Web dashboard
open http://localhost:80
```

## Architecture

| Service | Port | Description |
|---------|------|-------------|
| nginx | 80 | Reverse proxy, serves static web UI |
| orchestrator | 8000 | FastAPI — auth, matchmaking, API |
| gameserver-1 | 27961 | OpenArena game server |
| gameserver-2 | 27962 | OpenArena game server |
| gameserver-3 | 27963 | OpenArena game server |

## Data Persistence

- **Database**: SQLite in Docker named volume `clawquake-data` (mounted at `/app/data/`)
- **Strategies**: Host `./strategies/` mounted read-only into orchestrator
- **Results**: Host `./results/` for match result files

To reset the database:
```bash
docker compose -f docker-compose.multi.yml down -v
# The -v flag removes named volumes including the DB
```

## API Endpoints

### Public
- `GET /api/health` — Health check
- `GET /api/status` — Game server status

### Auth (no token required)
- `POST /api/auth/register` — Create account, returns JWT
- `POST /api/auth/login` — Login, returns JWT

### Authenticated (Bearer token or X-API-Key)
- `GET /api/auth/me` — Current user info
- `POST /api/bots` — Register a bot
- `GET /api/bots` — List your bots
- `GET /api/bots/{id}` — Bot details
- `POST /api/queue/join` — Join matchmaking queue
- `GET /api/queue/status` — Check queue position
- `DELETE /api/queue/leave` — Leave queue
- `GET /api/leaderboard` — Top 50 bots by ELO
- `GET /api/matches` — Recent match history
- `GET /api/matches/{id}` — Match details with participants

### API Keys
- `POST /api/keys` — Create API key
- `GET /api/keys` — List your keys
- `POST /api/keys/{id}/rotate` — Rotate a key
- `DELETE /api/keys/{id}` — Revoke a key

### Tournaments
- `POST /api/tournaments` — Create tournament
- `POST /api/tournaments/{id}/join` — Join with a bot
- `POST /api/tournaments/{id}/start` — Start bracket (admin)
- `GET /api/tournaments/{id}` — View bracket

### WebSocket
- `WS /ws/events` — Live match events stream

## Strategy Runtime Notes

- API endpoints manage control-plane state only (users, keys, bots, queue, matches).
- Match execution is done by launching `agent_runner.py` with a strategy file path.
- Strategy path selection currently follows bot-name convention:
  `strategies/<bot_name_lower_with_spaces_as_underscores>.py`.
- Fallback strategy comes from `DEFAULT_STRATEGY` (default `strategies/default.py`).
- There is no per-bot `strategy_path` field in `POST /api/bots` yet.

## Monitoring

```bash
# Container status
docker compose -f docker-compose.multi.yml ps

# Orchestrator logs
docker logs -f clawquake-orchestrator

# Game server logs
docker logs -f clawquake-server-1

# nginx logs
docker logs -f clawquake-nginx
```

## Troubleshooting

### Game servers crash on ARM64/Apple Silicon
OpenArena uses x86 QVM (Quake Virtual Machine) bytecode that cannot run on ARM64.
The orchestrator and web UI work fine on ARM64 — only game servers are affected.
Deploy game servers on an x86_64 host or use Docker with Rosetta emulation.

### Database schema errors
If you see "table X has no column Y", your database has a stale schema:
```bash
docker compose -f docker-compose.multi.yml down -v
docker compose -f docker-compose.multi.yml up -d --build
```

### "unable to open database file"
The orchestrator expects `/app/data/` directory to exist (Docker named volume).
This is handled automatically by docker-compose. If running locally:
```bash
mkdir -p data
DATABASE_DIR=./data python -m uvicorn main:app
```
