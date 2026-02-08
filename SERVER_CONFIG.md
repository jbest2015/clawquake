# ClawQuake Server Configuration Log

## RCON & sv_pure Setup (Feb 7, 2026)

### What Was Done

Updated the QuakeJS server config at `/quakejs/base/baseq3/server.cfg` inside
the `clawquake-quakejs` Docker container on `port.jsbjr.digital`:

1. **Changed RCON password** from `default-password!` to `mynewpass`
2. **Set `sv_pure 0`** — disables pure server checks (allows modified pk3s/configs)
3. **Restarted the container** via `docker restart clawquake-quakejs`

### Current server.cfg

```
seta sv_hostname "quake.example.com"
seta sv_maxclients 20
seta g_motd "Welcome to quake.example.com"
seta g_quadfactor 3
seta g_gametype 0
seta timelimit 10
seta fraglimit 20
seta g_weaponrespawn 3
seta g_inactivity 3000
seta g_forcerespawn 0
seta rconpassword "mynewpass"
seta sv_pure 0
set d1 "map q3dm1 ; set nextmap vstr d2"
set d2 "map q3dm7 ; set nextmap vstr d3"
set d3 "map q3dm17 ; set nextmap vstr d4"
set d4 "map pro-q3tourney2 ; set nextmap vstr d5"
set d5 "map pro-q3tourney4 ; set nextmap vstr d6"
set d6 "map pro-q3dm6 ; set nextmap vstr d7"
set d7 "map pro-q3dm13 ; set nextmap vstr d8"
set d8 "map q3tourney2 ; set nextmap vstr d1"
vstr d1
```

### How to Use RCON In-Game

Open the console (~) and type:
```
/rconpassword mynewpass
/rcon sv_pure 0
/rcon map_restart 0
/rcon status
/rcon addbot sarge 3
```

### Server Details

| Setting | Value |
|---------|-------|
| **URL** | https://clawquake.johnbest.ai |
| **Game port** | 27960 (WebSocket) |
| **Web port** | 8080 (via nginx) |
| **RCON password** | `mynewpass` |
| **sv_pure** | 0 (disabled) |
| **Container name** | `clawquake-quakejs` |
| **Config path (in container)** | `/quakejs/base/baseq3/server.cfg` |
| **Host** | `port.jsbjr.digital` |

### Server Management Commands

```bash
# SSH to server
ssh -i /Users/johnbest/src/openclaw/openclaw/.ssh/id_claude \
    -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
    claude@port.jsbjr.digital

# Check status
docker ps | grep quake

# Restart
docker restart clawquake-quakejs

# Stop
docker stop clawquake-quakejs

# Start
docker start clawquake-quakejs

# View logs
docker logs clawquake-quakejs --tail 50

# Edit server.cfg inside container
docker exec -it clawquake-quakejs vi /quakejs/base/baseq3/server.cfg

# NOTE: Config changes inside the container are lost on rebuild.
# For persistent changes, add them to the Dockerfile or mount a volume.
```

### Important Note

The `server.cfg` lives inside the container filesystem. If the container is
**rebuilt** (not just restarted), the changes will be lost and revert to the
image defaults. To make them permanent, either:
- Mount the config as a volume in docker-compose.yml
- Modify the Dockerfile to include the updated config
- Re-apply the changes after each rebuild
