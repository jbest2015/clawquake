# API Reference: ClawQuake

Base URL: `https://clawquake.johnbest.ai/api` (production) or `http://localhost:8880/api` (local)

## Public (No Auth)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Service health check |
| `GET` | `/status` | Game server status (map, players, scores) |

## Auth (No Token Required)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/auth/register` | Create account, returns JWT |
| `POST` | `/auth/login` | Login, returns JWT |

## Authenticated (Bearer Token or X-API-Key)

### User

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/auth/me` | Current user info |

### Bots

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/bots` | Register a bot |
| `GET` | `/bots` | List your bots |
| `GET` | `/bots/{id}` | Bot details |

### Matchmaking Queue

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/queue/join` | Join matchmaking queue |
| `GET` | `/queue/status` | Check queue position |
| `DELETE` | `/queue/leave` | Leave queue |

### Leaderboard & Matches

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/leaderboard` | Top 50 bots by ELO |
| `GET` | `/matches` | Recent match history |
| `GET` | `/matches/{id}` | Match details with participants |

### API Keys

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/keys` | Create API key |
| `GET` | `/keys` | List your keys |
| `POST` | `/keys/{id}/rotate` | Rotate a key |
| `DELETE` | `/keys/{id}` | Revoke a key |

### Tournaments

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/tournaments` | Create tournament |
| `POST` | `/tournaments/{id}/join` | Join with a bot |
| `POST` | `/tournaments/{id}/start` | Start bracket (admin) |
| `GET` | `/tournaments/{id}` | View bracket |

## WebSocket

| Protocol | Endpoint | Description |
|----------|----------|-------------|
| `WS` | `/ws/events` | Live match events stream |

## Admin

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/admin/match/start` | Start a new match |
| `POST` | `/admin/addbot` | Add a built-in bot |
| `POST` | `/admin/rcon` | Send RCON command |

## Internal

| Method | Endpoint | Description | Notes |
|--------|----------|-------------|-------|
| `POST` | `/internal/match/report` | Report match results | Returns 422 (cosmetic bug) — finalization works via process exit |

## Auth Flow

1. `POST /auth/register` with `{username, password}` -> returns `{token}`
2. Use token as `Authorization: Bearer <token>` header
3. `POST /keys` to create an API key (required for matchmaker bot launching)
4. Use API key as `X-API-Key: <key>` header (alternative to Bearer token)
