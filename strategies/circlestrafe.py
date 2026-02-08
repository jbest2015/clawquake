"""
Circle-strafing strategy: orbits enemy while maintaining fire.

Keeps medium distance, circle-strafes around the target,
switches direction periodically to be unpredictable.
"""

STRATEGY_NAME = "Circle Strafer"
STRATEGY_VERSION = "1.0"

import random


def on_spawn(ctx):
    """Initialize per-match state."""
    ctx.strafe_dir = 1       # 1 = left, -1 = right
    ctx.switch_timer = 0
    ctx.ideal_distance = 400  # Try to maintain this distance
    ctx.switch_interval = random.randint(20, 60)


async def tick(bot, game, ctx):
    """Called every game tick (~20Hz). Return list of action strings."""
    actions = []
    nearest = game.nearest_player()

    if not nearest:
        # Explore -- move forward with random turns
        actions.append("move_forward")
        if random.random() < 0.1:
            actions.append(f"turn_right {random.randint(20, 60)}")
        return actions

    pos = nearest['position']
    dist = game.distance_to(pos)

    # Always aim at target
    actions.append(f"aim_at {pos[0]} {pos[1]} {pos[2]}")

    # Always shoot when we can see someone
    actions.append("attack")

    # Distance management
    if dist > ctx.ideal_distance + 200:
        actions.append("move_forward")
    elif dist < ctx.ideal_distance - 100:
        actions.append("move_back")

    # Circle strafe
    if ctx.strafe_dir > 0:
        actions.append("move_left")
    else:
        actions.append("move_right")

    # Switch strafe direction periodically
    ctx.switch_timer += 1
    if ctx.switch_timer > ctx.switch_interval:
        ctx.strafe_dir *= -1
        ctx.switch_timer = 0
        ctx.switch_interval = random.randint(20, 60)

    # Dodge jump
    if random.random() < 0.05:
        actions.append("jump")

    return actions
