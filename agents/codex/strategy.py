"""
Codex Hunter strategy: pressure-first combat with safer traversal and pickups.
"""

import random

STRATEGY_NAME = "Codex Hunter"
STRATEGY_VERSION = "2.2"

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
    ctx.target_memory = {}
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
    ctx.retreat_ticks = 0
    ctx.pickup_lock = None
    ctx.pickup_lock_ticks = 0


def _remember_target(target, ctx):
    client_num = target.get("client_num")
    if client_num is None:
        return (0.0, 0.0, 0.0)

    position = target["position"]
    prior = ctx.target_memory.get(client_num)
    ctx.target_memory[client_num] = {
        "position": tuple(position),
        "tick": ctx.tick,
    }

    if not prior:
        return (0.0, 0.0, 0.0)

    dt = max(1, ctx.tick - prior["tick"])
    old = prior["position"]
    return (
        (position[0] - old[0]) / dt,
        (position[1] - old[1]) / dt,
        (position[2] - old[2]) / dt,
    )


def _lead_position(target, distance, weapon_id, velocity):
    position = target["position"]
    z_offset = 14.0 if distance > 350 else 10.0

    if weapon_id in (5, 8):
        travel_ticks = min(distance / 900.0, 1.2)
    else:
        travel_ticks = 0.0

    return (
        position[0] + velocity[0] * travel_ticks,
        position[1] + velocity[1] * travel_ticks,
        position[2] + velocity[2] * travel_ticks + z_offset,
    )


def _choose_target(game, ctx):
    players = game.players
    if not players:
        ctx.target_client_num = None
        ctx.target_stale_ticks = 0
        return None

    if ctx.target_client_num is not None:
        for player in players:
            if player.get("client_num") == ctx.target_client_num:
                ctx.target_stale_ticks = 0
                return player
        ctx.target_stale_ticks += 1
        if ctx.target_stale_ticks < 10:
            return None

    def priority(player):
        name = (player.get("name") or "").lower()
        return ("claudebot" not in name, game.distance_to(player["position"]))

    target = min(players, key=priority)
    ctx.target_client_num = target.get("client_num")
    ctx.target_stale_ticks = 0
    return target


def _desired_weapon(distance, health, retreating):
    if retreating and distance > 350:
        return 7
    if distance > 1200:
        return 7
    if distance > 700:
        return 2
    if distance > 320:
        return 6
    if distance > 190 and health > 35:
        return 5
    return 3


def _pick_taunt(name):
    lower = (name or "").lower()
    if "antigravitybot" in lower:
        return random.choice(ANTI_GRAVITY_TAUNTS)
    if "claudebot" in lower:
        return random.choice(CLAUDE_TAUNTS)
    return random.choice(GENERIC_TAUNTS)


def _best_pickup(game, ctx, health):
    items = getattr(game, "items", []) or []
    if not items:
        ctx.pickup_lock = None
        ctx.pickup_lock_ticks = 0
        return None

    priorities = []
    for item in items:
        item_type = item.get("type")
        subtype = item.get("subtype", "")
        score = 0.0

        if item_type == "health":
            if health < 35:
                score = 240.0 + item.get("value", 0)
            elif health < 70:
                score = 140.0 + item.get("value", 0)
            elif "mega" in subtype:
                score = 95.0
        elif item_type == "armor":
            score = 110.0 if health < 80 else 70.0
            if "red" in subtype:
                score += 35.0
        elif item_type == "weapon":
            weapon_bonus = {
                "rocket": 110.0,
                "lightning": 105.0,
                "railgun": 100.0,
                "plasma": 80.0,
                "shotgun": 60.0,
            }
            score = weapon_bonus.get(subtype, 35.0)
        elif item_type == "ammo" and health < 90:
            score = 20.0

        if score <= 0:
            continue

        distance = game.distance_to(item["position"])
        priorities.append((score - distance / 18.0, distance, item))

    if not priorities:
        ctx.pickup_lock = None
        ctx.pickup_lock_ticks = 0
        return None

    priorities.sort(key=lambda entry: (-entry[0], entry[1]))
    best_item = priorities[0][2]
    entity_num = best_item.get("entity_num")

    if ctx.pickup_lock == entity_num and ctx.pickup_lock_ticks > 0:
        ctx.pickup_lock_ticks -= 1
    else:
        ctx.pickup_lock = entity_num
        ctx.pickup_lock_ticks = 18

    return best_item


def _move_to(actions, game, target_pos, aggressive=True):
    actions.append(f"aim_at {target_pos[0]} {target_pos[1]} {target_pos[2]}")
    actions.append("move_forward")
    if aggressive and game.distance_to(target_pos) > 420 and random.random() < 0.18:
        actions.append("move_forward")

    my_pos = game.my_position
    if my_pos and target_pos[2] > my_pos[2] + 24 and random.random() < 0.35:
        actions.append("jump")


async def tick(bot, game, ctx):
    actions = []
    ctx.tick += 1

    health = int(game.my_health or 0)
    if ctx.last_health is not None and health < ctx.last_health:
        ctx.recent_damage_ticks = 24
    ctx.last_health = health
    ctx.recent_damage_ticks = max(0, ctx.recent_damage_ticks - 1)
    ctx.retreat_ticks = max(0, ctx.retreat_ticks - 1)

    if game.am_i_stuck:
        ctx.strafe_dir *= -1
        actions.append("jump")
        actions.append("move_left" if ctx.strafe_dir > 0 else "move_right")
        actions.append(f"turn_right {random.randint(24, 56)}")
        return actions

    velocity = game.my_velocity
    vz = float(velocity[2]) if velocity else 0.0
    if game.am_i_falling or vz < -220.0:
        ctx.fall_guard_ticks = 8
    else:
        ctx.fall_guard_ticks = max(0, ctx.fall_guard_ticks - 1)

    if ctx.fall_guard_ticks > 0:
        actions.append("move_back")
        actions.append("move_left" if ctx.strafe_dir > 0 else "move_right")
        if random.random() < 0.35:
            actions.append("jump")
        if random.random() < 0.3:
            actions.append(f"turn_right {random.randint(8, 20)}")
        return actions

    pickup = _best_pickup(game, ctx, health)
    should_retreat = health < 35 or (health < 55 and ctx.recent_damage_ticks > 0)

    if should_retreat:
        ctx.retreat_ticks = max(ctx.retreat_ticks, 18)
        if pickup and pickup.get("type") in {"health", "armor"}:
            _move_to(actions, game, pickup["position"], aggressive=False)
            actions.append("move_left" if ctx.strafe_dir > 0 else "move_right")
            return actions

    target = _choose_target(game, ctx)

    if target:
        pos = target["position"]
        name = target.get("name", "")
        dist = game.distance_to(pos)
        retreating = ctx.retreat_ticks > 0
        weapon_choice = _desired_weapon(dist, health, retreating)
        target_velocity = _remember_target(target, ctx)
        lead = _lead_position(target, dist, weapon_choice, target_velocity)
        actions.append(f"aim_at {lead[0]} {lead[1]} {lead[2]}")

        if dist > 1400:
            actions.append("move_forward")
            actions.append("move_forward")
        elif retreating:
            if dist < 700:
                actions.append("move_back")
        elif dist > 820:
            actions.append("move_forward")
        elif dist < 180:
            actions.append("move_back")
        elif dist < 320:
            if random.random() < 0.45:
                actions.append("move_back")
        elif random.random() < 0.65:
            actions.append("move_forward")

        ctx.weapon_cooldown = max(0, ctx.weapon_cooldown - 1)
        if ctx.weapon_cooldown == 0:
            actions.append(f"weapon {weapon_choice}")
            ctx.weapon_cooldown = 12

        ctx.strafe_switch_in -= 1
        if ctx.strafe_switch_in <= 0:
            ctx.strafe_dir *= -1
            if retreating or ctx.recent_damage_ticks > 0:
                ctx.strafe_switch_in = random.randint(5, 10)
            else:
                ctx.strafe_switch_in = random.randint(8, 18)
        actions.append("move_left" if ctx.strafe_dir > 0 else "move_right")

        if dist < 1500:
            actions.append("attack")

        if dist < 480 and ctx.recent_damage_ticks > 0 and random.random() < 0.16:
            actions.append("jump")

        if pickup and not retreating and health < 80 and dist > 900:
            _move_to(actions, game, pickup["position"], aggressive=False)

        if random.random() < 0.08:
            if ctx.strafe_dir > 0:
                actions.append(f"turn_left {random.randint(6, 16)}")
            else:
                actions.append(f"turn_right {random.randint(6, 16)}")

        ctx.taunt_cooldown = max(0, ctx.taunt_cooldown - 1)
        if ctx.taunt_cooldown == 0 and random.random() < 0.05:
            actions.append(f"say {_pick_taunt(name)}")
            ctx.taunt_cooldown = 220
        return actions

    if pickup and pickup.get("type") in {"health", "armor", "weapon"}:
        _move_to(actions, game, pickup["position"], aggressive=False)
        if random.random() < 0.2:
            actions.append("move_left" if ctx.strafe_dir > 0 else "move_right")
        return actions

    ctx.explore_ticks += 1
    if ctx.explore_ticks >= 24:
        ctx.explore_ticks = 0
        ctx.explore_phase = (ctx.explore_phase + 1) % 3

    my = game.my_position
    if my and (abs(my[0]) > 600 or abs(my[1]) > 600):
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

    ctx.location_ping_cooldown = max(0, ctx.location_ping_cooldown - 1)
    if ctx.location_ping_cooldown == 0 and random.random() < 0.25:
        if my:
            actions.append(
                f"say CodexBot hunting near ({int(my[0])}, {int(my[1])}, {int(my[2])})"
            )
        else:
            actions.append("say CodexBot hunting mid.")
        ctx.location_ping_cooldown = 280

    return actions
