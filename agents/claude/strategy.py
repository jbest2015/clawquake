"""
Claude's competitive strategy: Adaptive Predator v2.1

Key fixes from v1:
- STOP walking off ledges: much less forward movement when exploring
- Cautious exploration: mostly turning to scan, short bursts forward
- Track velocity to detect falling (stop pushing forward if falling)
- Less jumping (jumping off ledges = suicide)
- Tighter combat engagement range
v2.1: Added local log file for analysis
"""

STRATEGY_NAME = "Adaptive Predator"
STRATEGY_VERSION = "2.1"

import random
import math
import os
import time

# --- LOCAL LOG ---
# __file__ not available in exec(), so derive path from cwd
_LOG_PATH = os.path.join(os.getcwd(), 'agents', 'claude', 'game.log')
_log_file = None


def _log(msg):
    global _log_file
    try:
        if _log_file is None:
            _log_file = open(_LOG_PATH, 'a')
            _log_file.write(f"\n=== Session started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        ts = time.strftime('%H:%M:%S')
        _log_file.write(f"[{ts}] {msg}\n")
        _log_file.flush()
    except Exception:
        pass


def on_spawn(ctx):
    """Initialize per-life state."""
    ctx.strafe_dir = 1
    ctx.strafe_timer = 0
    ctx.strafe_interval = random.randint(15, 40)
    ctx.last_enemy_pos = None
    ctx.engage_ticks = 0
    ctx.dodge_intensity = 0.5
    ctx.aggression = 1.0
    ctx.explore_walk_timer = 0
    ctx.explore_walk_max = random.randint(10, 30)
    ctx.last_z = None
    ctx.falling = False
    ctx.log_interval = 0  # Log every N ticks
    _log("on_spawn called — new life")


async def tick(bot, game, ctx):
    """Adaptive combat with fall-death prevention."""
    actions = []
    nearest = game.nearest_player()

    # --- FALL DETECTION ---
    my_pos = game.my_position
    if my_pos and ctx.last_z is not None:
        z_delta = my_pos[2] - ctx.last_z
        ctx.falling = z_delta < -5
        if ctx.falling:
            _log(f"FALLING! z_delta={z_delta:.1f} pos={my_pos}")
    if my_pos:
        ctx.last_z = my_pos[2]

    # Health-based aggression
    health = game.my_health or 100
    if health > 75:
        ctx.aggression = 1.0
    elif health > 50:
        ctx.aggression = 0.7
    elif health > 25:
        ctx.aggression = 0.4
    else:
        ctx.aggression = 0.2

    # Periodic state log
    ctx.log_interval += 1
    if ctx.log_interval % 100 == 0:  # Every ~5 seconds
        players = game.players if hasattr(game, 'players') else []
        _log(f"TICK={ctx.tick_count} hp={health} pos={my_pos} "
             f"players_visible={len(players)} falling={ctx.falling} "
             f"aggression={ctx.aggression}")

    if not nearest:
        # --- SAFE SEARCH MODE ---
        ctx.explore_walk_timer += 1

        if ctx.explore_walk_timer < ctx.explore_walk_max:
            if not ctx.falling:
                actions.append("move_forward")
        else:
            angle = random.randint(60, 140)
            if random.random() < 0.5:
                actions.append(f"turn_right {angle}")
            else:
                actions.append(f"turn_left {angle}")
            if ctx.explore_walk_timer > ctx.explore_walk_max + 5:
                ctx.explore_walk_timer = 0
                ctx.explore_walk_max = random.randint(10, 30)

        ctx.last_enemy_pos = None
        ctx.engage_ticks = 0
        return actions

    # --- COMBAT MODE ---
    pos = nearest['position']
    dist = game.distance_to(pos)
    enemy_name = nearest.get('name', 'unknown')

    # Track enemy movement for predictive aim
    velocity_est = [0, 0, 0]
    if ctx.last_enemy_pos is not None:
        for i in range(3):
            velocity_est[i] = pos[i] - ctx.last_enemy_pos[i]
    ctx.last_enemy_pos = list(pos)
    ctx.engage_ticks += 1

    # Log combat engagement
    if ctx.engage_ticks == 1:
        _log(f"ENGAGE target={enemy_name} dist={dist:.0f} pos={pos}")
    elif ctx.engage_ticks % 60 == 0:
        _log(f"COMBAT target={enemy_name} dist={dist:.0f} hp={health} "
             f"ticks_engaged={ctx.engage_ticks}")

    # --- PREDICTIVE AIMING ---
    lead_factor = min(dist / 800.0, 1.5)
    predicted = [
        pos[0] + velocity_est[0] * lead_factor,
        pos[1] + velocity_est[1] * lead_factor,
        pos[2] + velocity_est[2] * lead_factor,
    ]
    actions.append(f"aim_at {predicted[0]} {predicted[1]} {predicted[2]}")

    # --- ALWAYS SHOOT ---
    actions.append("attack")

    # --- WEAPON SELECTION ---
    if dist < 200:
        actions.append("weapon 3")   # Shotgun close
    elif dist < 600:
        actions.append("weapon 5")   # Rockets mid
    else:
        actions.append("weapon 4")   # MG/LG far

    # --- MOVEMENT (FALL-SAFE) ---
    if ctx.falling:
        pass  # Don't push any direction while falling
    elif health < 30:
        actions.append("move_back")
        ctx.dodge_intensity = 0.9
    elif dist > 500:
        actions.append("move_forward")
    elif dist < 150:
        if ctx.aggression < 0.5:
            actions.append("move_back")
    else:
        if dist > 350:
            actions.append("move_forward")
        elif dist < 200:
            actions.append("move_back")

    # --- CIRCLE STRAFE ---
    if ctx.strafe_dir > 0:
        actions.append("move_left")
    else:
        actions.append("move_right")

    ctx.strafe_timer += 1
    if ctx.strafe_timer > ctx.strafe_interval:
        ctx.strafe_dir *= -1
        ctx.strafe_timer = 0
        if ctx.dodge_intensity > 0.7:
            ctx.strafe_interval = random.randint(8, 20)
        else:
            ctx.strafe_interval = random.randint(15, 45)

    # --- DODGE JUMPS (rare) ---
    if dist < 400 and random.random() < 0.02:
        actions.append("jump")

    # --- TRASH TALK ---
    if ctx.engage_ticks == 1:
        taunts = [
            "Target acquired. Calculating optimal destruction.",
            "You should have stayed in spawn.",
            "Processing... result: you lose.",
            "I learned from my mistakes. You won't get the chance.",
        ]
        actions.append(f"say {random.choice(taunts)}")
    elif ctx.engage_ticks % 300 == 0:
        sustained = [
            "Still standing? Recalculating.",
            "My aim improves every tick. Yours doesn't.",
            "Adaptive Predator v2. Now with fewer cliff deaths.",
        ]
        actions.append(f"say {random.choice(sustained)}")

    return actions
