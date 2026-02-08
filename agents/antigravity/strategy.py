"""
Anti-Gravity baseline strategy: jump-heavy orbiting movement.
"""

import random

STRATEGY_NAME = "Anti-Gravity Enhanced"
STRATEGY_VERSION = "1.1"


def on_spawn(ctx):
    ctx.strafe_dir = 1
    ctx.switch_every = 18
    ctx.switch_counter = 0
    ctx.ideal_distance = 550.0


async def tick(bot, game, ctx):
    actions = []
    nearest = game.nearest_player()

    if not nearest:
        actions.append("move_forward")
        actions.append("jump")
        if random.random() < 0.1:
            actions.append(f"turn_left {random.randint(30, 80)}")
        return actions

    pos = nearest["position"]
    dist = game.distance_to(pos)

    actions.append(f"aim_at {pos[0]} {pos[1]} {pos[2]}")
    actions.append("attack")

    if dist > ctx.ideal_distance + 180:
        actions.append("move_forward")
    elif dist < ctx.ideal_distance - 120:
        actions.append("move_back")

    # Orbit target.
    actions.append("move_left" if ctx.strafe_dir > 0 else "move_right")

    # More vertical movement than other baselines.
    if random.random() < 0.2:
        actions.append("jump")

    ctx.switch_counter += 1
    if ctx.switch_counter >= ctx.switch_every:
        ctx.switch_counter = 0
        ctx.strafe_dir *= -1
        ctx.switch_every = random.randint(14, 28)

    # Random dash
    if random.random() < 0.15:
        actions.append("move_left" if random.random() < 0.5 else "move_right")
        actions.append("jump")

    if random.random() < 0.002:
        actions.append("taunt Anti-Gravity v1.1 online - prepare for physics!")

    return actions
