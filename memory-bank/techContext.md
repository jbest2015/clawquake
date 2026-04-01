# Tech Context: ClawQuake

## Technologies

| Layer | Technology | Version/Notes |
|-------|-----------|---------------|
| Game Engine | QuakeJS (ioquake3 port) | Protocol 71 (not vanilla Q3 Protocol 68) |
| Backend | FastAPI + Uvicorn | Python async, subprocess-based bot spawning |
| Database | SQLite | Named Docker volume at `/app/data/clawquake.db` |
| Auth | JWT + API Keys | Bearer token or X-API-Key header |
| Bot Client | Python + q3huff2 C lib | WebSocket Q3 protocol, Huffman compression |
| Streaming | Xvfb + LLVMpipe + FFmpeg | Software GL -> HLS |
| Frontend | Vanilla HTML/CSS/JS + hls.js | Static files served by nginx |
| Proxy | nginx | Reverse proxy + static file serving |
| Deploy | Docker Compose | Local (1 server) and production (3 servers) |

## Development Environment

- **GitHub**: `jbest2015/clawquake`
- **Dev server**: `docker compose up --build` -> `http://localhost:8880`
- **Tests**: `pytest` — 175 unit tests
- **Lint**: N/A (not currently configured)

## Constraints

- Game servers require x86_64 (QVM bytecode) — ARM64/Apple Silicon can only run orchestrator + web
- QuakeJS Protocol 71 differs significantly from vanilla Q3 Protocol 68
- q3huff2 C extension required — pure Python Huffman not compatible with QuakeJS
- Bot names must be globally unique
- API keys required for matchmaker bot launching

## Dependencies

- q3huff2 (C extension for Huffman coding)
- FastAPI, Uvicorn, SQLAlchemy
- websockets (Python async WebSocket client)
- Docker + Docker Compose

## Data Flow

1. User registers via API -> JWT issued
2. User creates API key -> registers bot -> joins queue
3. Matchmaker polls queue every 5s, pairs 2+ bots
4. Orchestrator spawns `agent_runner.py` subprocess per bot
5. Bot connects via WebSocket to game server (Protocol 71 handshake)
6. Strategy `tick()` runs each frame: reads game state, returns actions
7. Match ends -> ELO calculated -> stats persisted to SQLite
8. Dashboard/spectator receives live events via WebSocket hub
