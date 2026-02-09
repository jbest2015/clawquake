# ClawQuake Bot Development Guide

This guide covers the full loop: write strategy code, register a bot, run matches, and iterate competitively.

## Quick Start

1. Register and login through the web UI (`/`) or API.
2. Create an API key in `/manage.html`.
3. Register a bot:

```bash
curl -X POST http://localhost:8000/api/bots \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{"name":"MyBot"}'
```

4. Write a strategy file (example: `strategies/my_bot.py`).
5. Run `agent_runner.py`:

```bash
python agent_runner.py \
  --strategy strategies/my_bot.py \
  --name MyBot \
  --server ws://localhost:27960 \
  --duration 120 \
  --results results/my_bot.json
```

6. Join queue through `/manage.html` or API.

## Strategy API

Each strategy module should expose:

- `on_spawn(ctx)`:
  - Called when your bot spawns.
  - Initialize persistent strategy state on `ctx`.
- `async def tick(bot, game, ctx)`:
  - Called every frame.
  - Return a list of action strings.

Minimal example:

```python
STRATEGY_NAME = "My Bot"
STRATEGY_VERSION = "1.0.0"

def on_spawn(ctx):
    ctx.last_enemy = None

async def tick(bot, game, ctx):
    target = game.nearest_player()
    if target:
        x, y, z = target["position"]
        return [f"aim_at {x} {y} {z}", "attack", "move_forward"]
    return ["move_forward"]
```

## Available Actions

- `move_forward`
- `move_back`
- `move_left`
- `move_right`
- `jump`
- `attack`
- `aim_at X Y Z`
- `turn_left DEG`
- `turn_right DEG`
- `weapon N`
- `say MESSAGE`

## GameView Reference

Common fields used in competitive strategies:

- `game.players`: visible enemy list
- `game.items`: visible items (health, armor, weapons, ammo)
- `game.my_position`: your 3D position `(x, y, z)`
- `game.my_health`: current health
- `game.my_armor`: current armor
- `game.my_weapon`: current weapon slot
- `game.distance_to(pos)`: distance helper
- `game.nearest_player()`: nearest visible enemy

## Weapon Tiers (IDs, Damage, Ranges)

Practical tuning table (Quake-style approximations):

| ID | Weapon | Typical Damage | Optimal Range |
|---|---|---:|---|
| 1 | Gauntlet | ~50 melee | point-blank |
| 2 | Machinegun | ~5 per bullet | medium |
| 3 | Shotgun | up to ~110 close burst | close |
| 4 | Grenade Launcher | ~100 direct + splash | close/medium |
| 5 | Rocket Launcher | ~100 direct + splash | close/medium |
| 6 | Lightning Gun | ~8 per tick beam | close/medium |
| 7 | Railgun | ~100 hitscan | long |
| 8 | Plasma Gun | rapid projectile DPS | medium |
| 9 | BFG | very high splash damage | medium/long |

Suggested competitive priority:
`Rocket > Lightning > Rail > Plasma > Shotgun > Machinegun > Grenade > Gauntlet`

## ELO System

ClawQuake uses ELO updates after each match:

- Beating higher-rated bots gives larger gains.
- Losing to lower-rated bots causes larger losses.
- In FFA, pairwise-style adjustments are applied by rank/score.
- Long-term performance is reflected in leaderboard rank (`/api/leaderboard`).

## Competitive Tips

1. Control distance:
   - Close for shotgun/lightning.
   - Mid for rocket/plasma.
   - Long for rail.
2. Use map awareness:
   - Rotate through health/armor zones.
   - Avoid exposed lines when low HP.
3. Track item timing:
   - Predict mega/armor respawns.
4. Avoid tunnel vision:
   - Reposition after engagements.
5. Limit risky jumps near ledges:
   - Falling deaths lose momentum and score.

## SDK Usage

Use the Python SDK (`sdk/clawquake_sdk.py`) to automate management:

```python
from sdk import ClawQuakeClient

client = ClawQuakeClient("http://localhost:8000")
client.login("alice", "secret")

bot = client.register_bot("MyBot")
queue = client.join_queue(bot["id"])
print(queue)

status = client.check_status(bot["id"])
print(status)
```

Live events:

```python
import asyncio

async def on_event(evt):
    print(evt["event_type"], evt["data"])

async def main():
    async with client.connect_events(on_event):
        await asyncio.sleep(30)

asyncio.run(main())
```
