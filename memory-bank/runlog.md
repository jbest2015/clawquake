# Run Log: ClawQuake

## Execution History

### 2025-02-09 — Session 5+6: Bug fixes and debug instrumentation
- **Command**: `docker compose up --build -d`
- **Status**: Success (local)
- **Notes**: Fixed strategy loader, subprocess logging, entity crashes. All 175 tests passing. Production NOT deployed.

### 2025-02-08 — Sessions 1-4: Initial build and protocol debugging
- **Command**: `docker compose up --build`
- **Status**: Success after multiple protocol fixes
- **Notes**: Built full stack from scratch. Major work on Protocol 71 client — fixed Huffman, fragment reassembly, delta compression, gamestate parsing. Matchmaker, dashboard, and spectator all brought online.

## Common Commands

```bash
# Dev — local stack
docker compose up --build -d
docker compose down

# Production — multi-server
docker compose -f docker-compose.multi.yml up -d --build
docker compose -f docker-compose.multi.yml down

# Tests
pytest

# Production SSH
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519 claude@port.jsbjr.digital

# Logs
docker logs -f clawquake-orchestrator
docker logs -f clawquake-server-1

# Health check
curl http://localhost:8880/api/health
```

## Error States Encountered & Resolution

- **q3huff2 segfault**: Buffer overflow — added `_bytes_read` tracking and `BufferOverflow` exception
- **Gamestate not loading**: 3 combined issues — unsigned sequence read, missing snap_flags, wrong entity delta format
- **Matchmaker not starting**: Missing asyncio startup task in `main.py`
- **Docker networking**: `localhost` doesn't resolve between containers — use service names
- **AGENT_RUNNER_PATH**: `os.path ..` resolves wrong in Docker — use absolute path

## Performance Metrics

- 175 unit tests: all passing
- Match duration: 120s default
- Matchmaker poll interval: 5s
- Strategy hot-reload interval: 5s
