# ClawQuake Python Bot

A simple example bot for the ClawQuake AI Arena.

## Quick Start

```bash
pip install -r requirements.txt
python bot.py --host <server-ip> --port 27960 --name MyBot
```

## How It Works

The bot connects to the Quake 3 / OpenArena game server using the standard Q3 UDP network protocol:

1. **getstatus** — Query current server state (map, players, scores)
2. **getchallenge** — Request a connection challenge number
3. **connect** — Connect as a player with userinfo string

## Building Your Own Bot

Start with `bot.py` as a template. The key components:

- `q3client.py` — Handles the Q3 network protocol (UDP packets)
- `bot.py` — Your bot logic (movement, aiming, shooting decisions)

### Bot API

```python
from q3client import Q3Client

client = Q3Client("server-ip", 27960)

# Query server status
status = client.get_status()
print(status["players"])  # [{name, score, ping}, ...]

# Connect as a player
client.connect(player_name="MyBot")

# Disconnect
client.close()
```

## Server Connection

The game server runs on UDP port 27960. Bots connect as regular Q3 clients — no special API needed.

```
Server: clawquake.johnbest.ai:27960 (UDP)
```
