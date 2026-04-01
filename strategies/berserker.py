"""
Berserker Strategy: Aggressive, constant, unpredictable movement.

Core philosophy: NEVER stop moving. Randomize movement patterns every few ticks
to make prediction nearly impossible. Close distance fast, shoot constantly,
and use erratic strafing + jumping to dodge incoming fire.
"""

import random
import math

STRATEGY_NAME = "Berserker"
STRATEGY_VERSION = "1.0"

# Weapon constants
WP_GAUNTLET = 1
WP_MACHINEGUN = 2
WP_SHOTGUN = 3
WP_GRENADE_LAUNCHER = 4
WP_ROCKET_LAUNCHER = 5
WP_LIGHTNING = 6
WP_RAILGUN = 7
WP_PLASMAGUN = 8
WP_BFG = 9

# Projectile speeds for lead aiming
PROJECTILE_SPEEDS = {
    WP_ROCKET_LAUNCHER: 900.0,
    WP_PLASMAGUN: 2000.0,
    WP_GRENADE_LAUNCHER: 700.0,
    WP_BFG: 2000.0,
}


def on_spawn(ctx):
    """Initialize per-match state."""
    ctx.move_pattern = 0          # Current movement pattern index
    ctx.pattern_timer = 0         # Ticks until next pattern switch
    ctx.pattern_duration = 0      # How long current pattern lasts
    ctx.strafe_dir = 1            # 1=left, -1=right
    ctx.jump_cooldown = 0         # Ticks until next jump allowed
    ctx.stuck_ticks = 0
    ctx.last_pos = None
    ctx.target_history = {}       # For lead aim prediction
    ctx.spin_angle = 0            # For spinning exploration
    ctx.aggro_charge = False      # Whether we're in a charge rush
    ctx.charge_timer = 0
    _new_pattern(ctx)


def _new_pattern(ctx):
    """Pick a new random movement pattern."""
    ctx.move_pattern = random.randint(0, 5)
    ctx.pattern_duration = random.randint(8, 25)  # 0.4s - 1.25s at 20Hz
    ctx.pattern_timer = ctx.pattern_duration
    ctx.strafe_dir = random.choice([1, -1])
    # 30% chance to enter aggro charge mode
    ctx.aggro_charge = random.random() < 0.3
    ctx.charge_timer = random.randint(15, 40) if ctx.aggro_charge else 0


def _choose_weapon(dist):
    """Aggressive weapon selection - favor high DPS at all ranges."""
    if dist < 80:
        return WP_SHOTGUN
    elif dist < 250:
        return random.choice([WP_PLASMAGUN, WP_ROCKET_LAUNCHER, WP_LIGHTNING])
    elif dist < 500:
        return random.choice([WP_ROCKET_LAUNCHER, WP_LIGHTNING, WP_PLASMAGUN])
    elif dist < 800:
        return random.choice([WP_RAILGUN, WP_ROCKET_LAUNCHER])
    else:
        return WP_RAILGUN


def _lead_aim(my_pos, target, weapon_id, ctx, server_time):
    """Predict where the target will be when our projectile arrives."""
    client_num = target.get('client_num', target.get('entity_number', -1))
    t_pos = target['position']

    history = ctx.target_history.get(client_num)
    velocity = [0.0, 0.0, 0.0]

    if history:
        old_pos = history['pos']
        dt = (server_time - history['time']) / 1000.0
        if 0 < dt < 1.0:
            velocity = [
                (t_pos[i] - old_pos[i]) / dt for i in range(3)
            ]

    ctx.target_history[client_num] = {'pos': list(t_pos), 'time': server_time}

    speed = PROJECTILE_SPEEDS.get(weapon_id)
    if not speed:
        # Hitscan - aim directly
        return t_pos

    dx = t_pos[0] - my_pos[0]
    dy = t_pos[1] - my_pos[1]
    dz = t_pos[2] - my_pos[2]
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist == 0:
        return t_pos

    time_to_impact = dist / speed
    lead = [t_pos[i] + velocity[i] * time_to_impact for i in range(3)]

    if weapon_id == WP_GRENADE_LAUNCHER:
        lead[2] += 0.5 * 800.0 * time_to_impact * time_to_impact

    return lead


def _evasion_moves(ctx):
    """Generate unpredictable evasion movement. NEVER returns empty."""
    actions = []
    pattern = ctx.move_pattern

    if pattern == 0:
        # Rapid strafe alternation
        actions.append("move_left" if ctx.strafe_dir > 0 else "move_right")
        if random.random() < 0.4:
            ctx.strafe_dir *= -1

    elif pattern == 1:
        # Diagonal rush: forward + strafe
        actions.append("move_forward")
        actions.append("move_left" if ctx.strafe_dir > 0 else "move_right")

    elif pattern == 2:
        # Zigzag: alternate strafe every 3 ticks
        if ctx.pattern_timer % 3 == 0:
            ctx.strafe_dir *= -1
        actions.append("move_left" if ctx.strafe_dir > 0 else "move_right")
        actions.append("move_forward")

    elif pattern == 3:
        # Backward dodge: retreat while strafing
        actions.append("move_back")
        actions.append("move_left" if random.random() < 0.5 else "move_right")

    elif pattern == 4:
        # Circle strafe burst: strafe + forward
        actions.append("move_left" if ctx.strafe_dir > 0 else "move_right")
        if random.random() < 0.5:
            actions.append("move_forward")

    elif pattern == 5:
        # Pure chaos: random direction each tick
        actions.append(random.choice([
            "move_forward", "move_back", "move_left", "move_right"
        ]))
        if random.random() < 0.5:
            actions.append(random.choice([
                "move_forward", "move_back", "move_left", "move_right"
            ]))

    # Jumping - high frequency for dodge, with cooldown to avoid bunny-hop penalty
    if ctx.jump_cooldown <= 0 and random.random() < 0.2:
        actions.append("jump")
        ctx.jump_cooldown = random.randint(3, 8)
    else:
        ctx.jump_cooldown = max(0, ctx.jump_cooldown - 1)

    return actions


async def tick(bot, game, ctx):
    """Called every game tick (~20Hz). Return list of action strings."""
    actions = []
    my_pos = game.my_position

    if not my_pos:
        return ["move_forward", "jump"]  # Not spawned yet, keep trying

    # Stuck detection
    if ctx.last_pos and game.distance_to(ctx.last_pos) < 3:
        ctx.stuck_ticks += 1
    else:
        ctx.stuck_ticks = 0
    ctx.last_pos = my_pos

    # Stuck recovery - aggressive escape
    if ctx.stuck_ticks > 15:
        actions.append("jump")
        actions.append(random.choice(["move_left", "move_right", "move_back"]))
        actions.append(f"turn_{random.choice(['left', 'right'])} {random.randint(60, 180)}")
        ctx.stuck_ticks = 0
        return actions

    # Pattern rotation - this is the core of unpredictability
    ctx.pattern_timer -= 1
    if ctx.pattern_timer <= 0:
        _new_pattern(ctx)

    # Find enemy
    target = game.nearest_player()

    if target:
        t_pos = target['position']
        dist = game.distance_to(t_pos)

        # Weapon selection
        weapon = _choose_weapon(dist)
        actions.append(f"weapon {weapon}")

        # Lead aim
        aim_pos = _lead_aim(my_pos, target, weapon, ctx, game.server_time)
        # Aim slightly above center mass
        actions.append(f"aim_at {aim_pos[0]} {aim_pos[1]} {aim_pos[2] + 12}")

        # ALWAYS attack - we're a berserker
        actions.append("attack")

        # Distance management: close the gap aggressively
        if ctx.aggro_charge and ctx.charge_timer > 0:
            # Full speed rush
            actions.append("move_forward")
            ctx.charge_timer -= 1
            # Still strafe while charging
            actions.append("move_left" if random.random() < 0.5 else "move_right")
            if random.random() < 0.15:
                actions.append("jump")
        elif dist > 600:
            # Far away: rush in with evasive movement
            actions.append("move_forward")
            actions.extend(_evasion_moves(ctx))
        elif dist > 200:
            # Mid range: full evasion while fighting
            actions.extend(_evasion_moves(ctx))
            # Drift forward to maintain pressure
            if random.random() < 0.4:
                actions.append("move_forward")
        else:
            # Close range: maximum chaos movement
            actions.extend(_evasion_moves(ctx))

    else:
        # No target: explore aggressively
        actions.append("move_forward")

        # Try to pick up items
        items = getattr(game, 'items', [])
        if items:
            useful = [i for i in items
                      if i.get('type') in ('health', 'armor', 'weapon', 'ammo')]
            if useful:
                nearest_item = min(useful,
                                   key=lambda i: game.distance_to(i['position']))
                i_pos = nearest_item['position']
                actions.append(f"aim_at {i_pos[0]} {i_pos[1]} {i_pos[2] + 10}")
                actions.append("move_forward")
                if i_pos[2] > my_pos[2] + 20:
                    actions.append("jump")
            else:
                # Spin and search
                ctx.spin_angle += random.randint(5, 15)
                if random.random() < 0.08:
                    actions.append(
                        f"turn_{random.choice(['left', 'right'])} "
                        f"{random.randint(20, 70)}"
                    )
        else:
            # No items visible - random exploration
            ctx.spin_angle += random.randint(5, 15)
            if random.random() < 0.08:
                actions.append(
                    f"turn_{random.choice(['left', 'right'])} "
                    f"{random.randint(20, 70)}"
                )

        # Keep moving unpredictably even while exploring
        if random.random() < 0.3:
            actions.append(random.choice(["move_left", "move_right"]))
        if random.random() < 0.1:
            actions.append("jump")

    return actions
