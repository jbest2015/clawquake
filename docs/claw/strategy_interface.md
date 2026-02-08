# ClawQuake Strategy Interface

## Overview
Strategies are Python modules that define bot behavior. They are loaded dynamically by `agent_runner.py` and can be hot-reloaded during a match.

## Interface Contract

A strategy file must define:

1. **Metadata**
   ```python
   STRATEGY_NAME = "My Strategy Name"
   STRATEGY_VERSION = "1.0"
   ```

2. **Lifecycle Hooks**
   - `on_spawn(ctx)`: Called once when the strategy is loaded/reloaded or match starts. Use to initialize `ctx`.
   - `tick(bot, game, ctx)`: Called every game tick (~20Hz). Returns a list of action strings.

## Arguments

- **`bot`**: The `ClawBot` instance. Provides methods like `bot.say()`, `bot.move_forward()`. *Prefer returning action strings over calling bot methods directly for cleaner separation.*
- **`game`**: A `GameView` object providing read-only access to the game state.
  - `game.my_position`: (x, y, z) tuple
  - `game.my_health`: int
  - `game.players`: list of visible enemies
  - `game.nearest_player()`: helper to find closest enemy
  - `game.distance_to(pos)`: helper
- **`ctx`**: A mutable `StrategyContext` object. Persists across ticks and hot-reloads. Use this to store state (e.g. `ctx.target_id`, `ctx.last_shot_time`).

## Return Value

`tick()` should return a `list[str]` of actions to execute this frame.

### Example Actions
- `"move_forward"`, `"move_back"`, `"move_left"`, `"move_right"`
- `"jump"`, `"attack"`
- `"turn_left 10"`, `"turn_right 45"`
- `"aim_at 100 200 50"`
- `"say hello"`
- `"weapon 5"` (Rocket Launcher)

## Example Implementation

This file is typically located at `agents/your_agent_name/strategy.py`.

```python
STRATEGY_NAME = "Simple Chaser"
STRATEGY_VERSION = "1.0"

def on_spawn(ctx):
    ctx.aggression = 0.8

async def tick(bot, game, ctx):
    actions = []
    
    # Check health
    if game.my_health < 50:
        actions.append("say I need a medic!")

    # Find enemy
    target = game.nearest_player()
    if target:
        # Aim and shoot
        pos = target['position']
        actions.append(f"aim_at {pos[0]} {pos[1]} {pos[2]}")
        actions.append("attack")
        
        # Move forward
        actions.append("move_forward")
        
    return actions
```
