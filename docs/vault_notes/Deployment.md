# Deployment: ClawQuake

## Prerequisites

- Docker and Docker Compose (v2+)
- Ports 80, 8000, 27961-27963 available
- x86_64 host for game servers (ARM64/Apple Silicon: orchestrator + web only)

## Environment Variables

Create `.env` from `.env.example`:

| Variable | Description | Example |
|----------|-------------|---------|
| `JWT_SECRET` | 256-bit secret for JWT signing | `openssl rand -hex 32` |
| `RCON_PASSWORD` | Game server remote console password | `my_rcon_pass` |
| `INTERNAL_SECRET` | Internal API auth between services | `my_internal_secret` |

## Local Development

```bash
# Full stack (x86_64 only)
docker compose up --build -d

# Visit http://localhost:8880
```

## Production

```bash
# Multi-server stack
docker compose -f docker-compose.multi.yml up -d --build

# Verify
curl http://localhost:80/api/health
```

### Production SSH

```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519 claude@port.jsbjr.digital
# Use docker-compose (hyphenated), may need sudo
```

## Services & Ports

| Service | Port | Description |
|---------|------|-------------|
| nginx | 80 | Reverse proxy, static web UI |
| orchestrator | 8000 | FastAPI — auth, matchmaking, API |
| gameserver-1 | 27961 | OpenArena game server |
| gameserver-2 | 27962 | OpenArena game server |
| gameserver-3 | 27963 | OpenArena game server |

## Data Persistence

- **Database**: SQLite in Docker named volume `clawquake-data` (mounted at `/app/data/`)
- **Strategies**: Host `./strategies/` mounted read-only into orchestrator
- **Results**: Host `./results/` for match result files

### Reset Database

```bash
docker compose -f docker-compose.multi.yml down -v
# -v flag removes named volumes including the DB
```

## Monitoring

```bash
docker compose -f docker-compose.multi.yml ps     # Container status
docker logs -f clawquake-orchestrator              # Orchestrator logs
docker logs -f clawquake-server-1                  # Game server logs
docker logs -f clawquake-nginx                     # nginx logs
```

## Troubleshooting

### Game servers crash on ARM64/Apple Silicon
OpenArena QVM bytecode cannot run on ARM64. Orchestrator + web work fine on ARM64. Deploy game servers on x86_64 or use Rosetta emulation.

### Database schema errors
Stale schema — nuke and rebuild:
```bash
docker compose -f docker-compose.multi.yml down -v
docker compose -f docker-compose.multi.yml up -d --build
```

### "unable to open database file"
Orchestrator expects `/app/data/` directory. For local (non-Docker) dev:
```bash
mkdir -p data
DATABASE_DIR=./data python -m uvicorn main:app
```

## Critical Docker Patterns

- Use **service names** (e.g., `gameserver-1`) not `localhost` for inter-container communication
- `AGENT_RUNNER_PATH` must be absolute in Docker (`os.path ..` resolves wrong)
- Protocol 71 spawn requires `sv_pure 0` + skip legacy begin
