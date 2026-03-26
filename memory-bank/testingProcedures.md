# Testing Procedures: ClawQuake

## Testing Standards

- **Unit tests**: pytest — 175 tests covering orchestrator, bot client, protocol, matchmaker
- **Integration tests**: Local Docker stack smoke tests (manual)
- **Manual testing**: Join as human player via QuakeJS spectator, observe bot behavior

## Test Commands

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_matchmaker.py

# Run specific test
pytest tests/test_matchmaker.py::test_elo_calculation
```

## Pre-Delivery Validation Steps

1. Run `pytest` — all 175 tests must pass
2. Build local Docker stack: `docker compose up --build -d`
3. Verify health: `curl http://localhost:8880/api/health`
4. Register user and create API key via API
5. Register bot and join queue
6. Verify matchmaker pairs bots and spawns processes
7. Check match results in dashboard

## Coverage Requirements

- All orchestrator API endpoints covered
- Protocol 71 handshake and frame parsing covered
- Matchmaker ELO calculation and pairing logic covered
- Strategy loader and hot-reload covered

## Testing Tools

- pytest
- Docker Compose (integration testing)
- curl / httpie (API smoke tests)
- QuakeJS browser client (manual spectating verification)
