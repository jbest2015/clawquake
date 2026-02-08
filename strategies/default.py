"""
Default strategy: chase nearest enemy, shoot, random strafe.

This is the baseline strategy that agents can clone and improve.
"""

STRATEGY_NAME = "Default Chaser"
STRATEGY_VERSION = "1.0"

import random


def on_spawn(ctx):
    """Initialize per-match state."""
    ctx.kills = 0
    ctx.deaths = 0
    ctx.engage_distance = 1000  # Shoot within this range


async def tick(bot, game, ctx):
    """Called every game tick (~20Hz). Return list of action strings."""
    actions = []
    nearest = game.nearest_player()

    if nearest:
        pos = nearest['position']
        dist = game.distance_to(pos)

        # Aim at enemy
        actions.append(f"aim_at {pos[0]} {pos[1]} {pos[2]}")

        # Move toward enemy
        actions.append("move_forward")

        # Shoot if close enough
        if dist < ctx.engage_distance:
            actions.append("attack")

        # Random strafe for evasion
        if random.random() < 0.3:
            actions.append("move_left" if random.random() < 0.5
                          else "move_right")

        # Jump occasionally
        if random.random() < 0.1:
            actions.append("jump")

    else:
        # No enemies visible -- explore
        actions.append("move_forward")

        # Random turns to search
        if random.random() < 0.1:
            actions.append(f"turn_right {random.randint(30, 90)}")

        # Occasional jump
        if random.random() < 0.05:
            actions.append("jump")

    return actions
