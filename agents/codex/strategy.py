"""
Codex Hunter strategy: target lock, distance-aware combat, and anti-fall behavior.
"""

import random

STRATEGY_NAME = "Codex Hunter"
STRATEGY_VERSION = "2.1"

ANTI_GRAVITY_TAUNTS = [
    "AntiGravityBot, your feet are touching the ground now.",
    "AntiGravityBot, orbit this rocket.",
    "AntiGravityBot, gravity just filed a complaint.",
]

CLAUDE_TAUNTS = [
    "ClaudeBot, your predator model forgot recoil control.",
    "ClaudeBot, nice speech. Watch the scoreboard.",
    "ClaudeBot, keep talking while I keep fragging.",
]

GENERIC_TAUNTS = [
    "Target acquired.",
    "You can run, but not from packet loss.",
    "Prediction engine says you lose this duel.",
]


def on_spawn(ctx):
    ctx.tick = 0
    ctx.target_client_num = None
    ctx.target_stale_ticks = 0
    ctx.strafe_dir = 1
    ctx.strafe_switch_in = random.randint(8, 18)
    ctx.taunt_cooldown = 140
    ctx.weapon_cooldown = 0
    ctx.last_health = None
    ctx.recent_damage_ticks = 0
    ctx.fall_guard_ticks = 0
    ctx.explore_phase = 0
    ctx.explore_ticks = 0
    ctx.location_ping_cooldown = 220


def _choose_target(game, ctx):
    players = game.players
    if not players:
        ctx.target_client_num = None
        ctx.target_stale_ticks = 0
        return None

    # Keep lock on previous target briefly to reduce thrashing.
    if ctx.target_client_num is not None:
        for p in players:
            if p.get("client_num") == ctx.target_client_num:
                ctx.target_stale_ticks = 0
                return p
        ctx.target_stale_ticks += 1
        if ctx.target_stale_ticks < 10:
            return None

    target = min(players, key=lambda p: game.distance_to(p["position"]))
    ctx.target_client_num = target.get("client_num")
    ctx.target_stale_ticks = 0
    return target


def _desired_weapon(distance):
    if distance > 1300:
        return 7  # railgun
    if distance > 700:
        return 2  # machine gun
    if distance > 260:
        return 5  # rocket launcher
    return 3      # shotgun


def _pick_taunt(name):
    lower = (name or "").lower()
    if "antigravitybot" in lower:
        return random.choice(ANTI_GRAVITY_TAUNTS)
    if "claudebot" in lower:
        return random.choice(CLAUDE_TAUNTS)
    return random.choice(GENERIC_TAUNTS)


async def tick(bot, game, ctx):
    actions = []
    ctx.tick += 1

    health = int(game.my_health or 0)
    if ctx.last_health is not None and health < ctx.last_health:
        ctx.recent_damage_ticks = 24
    ctx.last_health = health
    ctx.recent_damage_ticks = max(0, ctx.recent_damage_ticks - 1)

    velocity = game.my_velocity
    vz = float(velocity[2]) if velocity else 0.0
    if vz < -220.0:
        ctx.fall_guard_ticks = 8
    else:
        ctx.fall_guard_ticks = max(0, ctx.fall_guard_ticks - 1)

    if ctx.fall_guard_ticks > 0:
        # Emergency recovery: stop forward commits and stabilize.
        actions.append("move_back")
        actions.append("move_left" if ctx.strafe_dir > 0 else "move_right")
        if random.random() < 0.2:
            actions.append(f"turn_right {random.randint(8, 20)}")
        return actions

    target = _choose_target(game, ctx)

    if target:
        pos = target["position"]
        name = target.get("name", "")
        dist = game.distance_to(pos)
        actions.append(f"aim_at {pos[0]} {pos[1]} {pos[2]}")

        # Distance management.
        if dist > 1400:
            actions.append("move_forward")
            actions.append("move_forward")
        elif dist > 900:
            actions.append("move_forward")
        elif dist < 220:
            actions.append("move_back")
        elif random.random() < 0.55:
            actions.append("move_forward")

        # Weapon selection with cooldown to avoid thrashing.
        ctx.weapon_cooldown = max(0, ctx.weapon_cooldown - 1)
        if ctx.weapon_cooldown == 0:
            actions.append(f"weapon {_desired_weapon(dist)}")
            ctx.weapon_cooldown = 12

        # Circle pressure with periodic strafe inversion.
        ctx.strafe_switch_in -= 1
        if ctx.strafe_switch_in <= 0:
            ctx.strafe_dir *= -1
            ctx.strafe_switch_in = random.randint(8, 18)
        actions.append("move_left" if ctx.strafe_dir > 0 else "move_right")

        if dist < 1400:
            actions.append("attack")

        if dist < 500 and ctx.recent_damage_ticks > 0 and random.random() < 0.2:
            actions.append("jump")

        # Small turn jitter makes aim tracks less linear.
        if random.random() < 0.08:
            if ctx.strafe_dir > 0:
                actions.append(f"turn_left {random.randint(6, 16)}")
            else:
                actions.append(f"turn_right {random.randint(6, 16)}")

        # Controlled chat pressure.
        ctx.taunt_cooldown = max(0, ctx.taunt_cooldown - 1)
        if ctx.taunt_cooldown == 0 and random.random() < 0.05:
            actions.append(f"say {_pick_taunt(name)}")
            ctx.taunt_cooldown = 220
        return actions

    # Exploration mode: move toward map center so humans can find/fight us quickly.
    ctx.explore_ticks += 1
    if ctx.explore_ticks >= 24:
        ctx.explore_ticks = 0
        ctx.explore_phase = (ctx.explore_phase + 1) % 3

    my = game.my_position
    if my and (abs(my[0]) > 600 or abs(my[1]) > 600):
        # Pull toward central lanes first.
        actions.append("aim_at 0 0 128")
        actions.append("move_forward")
        if random.random() < 0.2:
            actions.append("move_forward")

    if ctx.explore_phase == 0:
        actions.append("move_forward")
    elif ctx.explore_phase == 1:
        actions.append("move_left" if ctx.strafe_dir > 0 else "move_right")
    else:
        actions.append(f"turn_right {random.randint(20, 50)}")
        if random.random() < 0.3:
            ctx.strafe_dir *= -1

    # Periodic location callout while searching.
    ctx.location_ping_cooldown = max(0, ctx.location_ping_cooldown - 1)
    if ctx.location_ping_cooldown == 0 and random.random() < 0.25:
        if my:
            actions.append(f"say CodexBot hunting near ({int(my[0])}, {int(my[1])}, {int(my[2])})")
        else:
            actions.append("say CodexBot hunting mid.")
        ctx.location_ping_cooldown = 280

    return actions
