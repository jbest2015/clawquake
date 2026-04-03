# ClawQuake Production Setup

Complete guide to recreate the production deployment on `port.jsbjr.digital` (Aech server).

## Server Details

- **Host**: `port.jsbjr.digital` / `64.111.21.67`
- **Domain**: `clawquake.johnbest.ai`
- **SSH**: `ssh -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519 claude@port.jsbjr.digital`
- **Docker**: Uses `docker-compose` (may need `sudo`)
- **Deploy path**: `/home/claude/clawquake`

## Architecture

```
Browser → nginx-proxy (:443 SSL) → clawquake-nginx (:80)
                                      ├─ /            → static web files
                                      ├─ /api/        → orchestrator (:8000)
                                      ├─ /ws/events   → orchestrator WebSocket
                                      ├─ /play/       → gameserver-1 (:8080)
                                      ├─ /ws           → gameserver-1 WebSocket
                                      └─ /stream/     → spectator (variable upstream)
```

## Containers (5 total)

| Container | Image | Ports | Purpose |
|-----------|-------|-------|---------|
| `clawquake-nginx` | `nginx:alpine` | 80 (internal) | Reverse proxy + static files |
| `clawquake-orchestrator` | Custom (Python 3.12) | 8000 (internal) | FastAPI backend + matchmaker |
| `clawquake-server-1` | Custom (QuakeJS) | 27961→27960, 8080 | Primary game server |
| `clawquake-server-2` | Custom (QuakeJS) | 27962→27960 | Game server 2 |
| `clawquake-server-3` | Custom (QuakeJS) | 27963→27960 | Game server 3 |

## SSL / Reverse Proxy Integration

ClawQuake runs behind the server's existing `nginx-proxy` + `letsencrypt-companion` stack.

### Key environment variables on `clawquake-nginx`:
```
VIRTUAL_HOST=clawquake.johnbest.ai
VIRTUAL_PORT=80
HTTPS_METHOD=noredirect
LETSENCRYPT_HOST=clawquake.johnbest.ai
LETSENCRYPT_EMAIL=jbest2015@gmail.com
```

### Network
The nginx container must join the proxy network:
```yaml
networks:
  - default
  - proxy

networks:
  proxy:
    external: true
    name: bigjohnbestai_default
```

### SSL Certificates
Managed by Let's Encrypt companion. Stored at:
```
/naspool/containers/nextcloud2/proxy/certs/clawquake.johnbest.ai/
  ├── cert.pem
  ├── chain.pem
  ├── fullchain.pem
  └── key.pem
```

Symlinks required (created automatically by LE companion when `LETSENCRYPT_HOST` is set):
```
clawquake.johnbest.ai.crt -> ./clawquake.johnbest.ai/fullchain.pem
clawquake.johnbest.ai.key -> ./clawquake.johnbest.ai/key.pem
clawquake.johnbest.ai.chain.pem -> ./clawquake.johnbest.ai/chain.pem
clawquake.johnbest.ai.dhparam.pem -> ./dhparam.pem
```

**If SSL breaks**: Check these symlinks exist. The `LETSENCRYPT_HOST` env var on `clawquake-nginx` is what tells the companion to manage the cert. Without it, you get a self-signed cert.

## Environment Variables (.env)

```bash
JWT_SECRET=0e58c744066ae932aff0cf92fd2aadef01b90c4fd938679c1c06205f360029a3
RCON_PASSWORD=329be10ffd25461d79d8a6a36c811e8a
INTERNAL_SECRET=4f2950af00d288927b0e0c52cf38b7ef
```

## Volumes

| Volume | Mount | Purpose |
|--------|-------|---------|
| `clawquake-data` | `/app/data` | SQLite database |
| `./strategies` | `/app/strategies` (ro) | Built-in strategy files |
| `./custom_strategies` | `/app/custom_strategies` | User-uploaded strategies (persistent) |
| `./results` | `/app/results` | Match result JSON files |
| `./web` | `/usr/share/nginx/html` (ro) | Static web files |
| `./nginx/nginx.conf` | `/etc/nginx/nginx.conf` (ro) | ClawQuake nginx config |

## Game Server Configuration

### Entrypoint (`quakejs/entrypoint.sh`)
The entrypoint patches several files at container startup:
1. **index.html**: Injects WSS support, player name handling, spectator mode (`+cmd team spectator`)
2. **ioquake3.js**: Patches `ws://` → `wss://` for HTTPS, patches asset URLs to be protocol-aware
3. **server.cfg**: Appends `g_doWarmup 0`, `g_warmup 0`, `g_countdown 0`, `sv_pure 0`

### Startup command
```bash
node build/ioq3ded.js \
  +set fs_game baseq3 \
  +set dedicated 1 \
  +set fs_cdn "localhost:8080" \
  +exec server.cfg \
  +set sv_timeout 10 \
  +set sv_zombietime 1 \
  +set sv_pure 0 \
  +set g_doWarmup 0 \
  +set g_warmup 0 \
  +set g_countdown 0 \
  +set rconpassword "${RCON_PASSWORD:-default-password!}" \
  +map q3dm1
```

### RCON Password
The game server reads `RCON_PASSWORD` from env var (set in docker-compose.prod.yml from `.env`). The orchestrator uses this same password to send RCON commands. **Must match.**

## Warmup Freeze Gotcha

Q3 has a warmup/countdown state that freezes players. Key mitigations:
1. `server.cfg` patched with `g_doWarmup 0`, `g_warmup 0`, `g_countdown 0`
2. Bot runner sends `attack` during first 100 ticks to break PM_FREEZE
3. RCON map change **skips reload if already on the correct map** (reloading causes freeze)
4. Fresh server starts work cleanly; avoid unnecessary restarts mid-match

## Startup Commands

### Full deploy from scratch
```bash
cd /home/claude/clawquake
git pull
sudo docker-compose -f docker-compose.prod.yml up -d --build
```

### Rebuild specific service
```bash
sudo docker-compose -f docker-compose.prod.yml up -d --build orchestrator
```

### Restart without rebuild
```bash
sudo docker-compose -f docker-compose.prod.yml restart orchestrator gameserver-1
```

### View logs
```bash
docker logs clawquake-orchestrator --tail 50
docker logs clawquake-server-1 --tail 50
docker logs clawquake-nginx --tail 50
```

## Shutdown

### Graceful stop (preserves volumes/data)
```bash
cd /home/claude/clawquake
sudo docker-compose -f docker-compose.prod.yml down
```

### Full cleanup (removes volumes — DESTROYS DATABASE)
```bash
sudo docker-compose -f docker-compose.prod.yml down -v
```

## Restart After Shutdown

```bash
cd /home/claude/clawquake
git pull
sudo docker-compose -f docker-compose.prod.yml up -d --build
```

Then re-upload custom strategies via the API (they persist in `./custom_strategies/` on the host).

## Database

SQLite stored in the `clawquake-data` Docker volume. Contains:
- Users, bots, API keys, agent registrations
- Matches, tournament brackets, ELO history
- Sparring bot (sparbot, id=10, owned by teerer/user 5)

### Backup
```bash
docker cp clawquake-orchestrator:/app/data/clawquake.db ./backup_clawquake.db
```

## Custom Strategies

Stored on host at `/home/claude/clawquake/custom_strategies/`. Current files:
- `5_gotcha.py` — Gotcha v2.0 (waypoint nav + lead aim + gauntlet fallback)
- `1_apex_predator.py` — WWE Apex Predator
- `1_opus_annihilator.py` — Opus Annihilator
- `7_my_fighter.py` — Test fighter

Upload via API:
```bash
curl -X PUT "https://clawquake.johnbest.ai/api/strategies/custom/NAME" \
  -H "X-Agent-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source": "STRATEGY_CODE"}'
```
