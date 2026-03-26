# Backup Details: ClawQuake

## Git Repository

- **Repository**: openclaw/clawquake
- **URL**: https://github.com/openclaw/clawquake
- **Local Path**: `/Users/johnbest/src/openclaw/clawquake`
- **Primary Branch**: `main`

## Remote Storage

- GitHub (source of truth)
- Docker named volume `clawquake-data` for SQLite DB on production server

## Production Infrastructure

- **Server**: `port.jsbjr.digital` (SSH as `claude` user)
- **URL**: `clawquake.johnbest.ai` / `port.jsbjr.digital`
- **SSH**: `ssh -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519 claude@port.jsbjr.digital`
- **Docker**: `docker-compose` (hyphenated), may need `sudo`
- **HTTPS**: jwilder/nginx-proxy (currently returning 500)

## Backup Procedures

1. Code: push to GitHub (`git push origin main`)
2. Database: SQLite file in Docker named volume — back up with `docker cp` or volume backup

## Recovery Procedures

1. Clone repo: `git clone https://github.com/openclaw/clawquake`
2. Create `.env` from `.env.example` with secrets
3. Build and start: `docker compose -f docker-compose.multi.yml up -d --build`
4. Database will be empty (fresh SQLite created on first run)
5. Re-register users and bots via API
