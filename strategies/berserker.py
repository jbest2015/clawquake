"""
Berserker Strategy v2.0: Aggressive, adaptive, unpredictable.

Core philosophy: NEVER stop moving. Rotate movement patterns every 0.4-1.25s
to make prediction nearly impossible. Adapt posture based on effective HP.
Use iterative lead aim with splash targeting for rockets. Time item respawns
and route toward them during retreat or roam phases.

v2.0 improvements over v1.0:
- Effective HP posture system (aggressive/neutral/retreat)
- Iterative lead aim (3-pass convergence)
- Splash aiming for rockets (feet for grounded, direct for airborne)
- Ammo-aware weapon selection with corrected LG range (384 max)
- Sinusoidal strafe mixed into pattern rotation
- Backpedal-while-firing retreat toward items
- Breadcrumb anti-loop exploration
- Item respawn timing
- Stale velocity entry cleanup
"""

import random
import math

STRATEGY_NAME = "Berserker"
STRATEGY_VERSION = "2.1"

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

# Projectile speeds (units/sec) for lead aiming. Hitscan weapons omitted.
PROJECTILE_SPEEDS = {
    WP_ROCKET_LAUNCHER: 900.0,
    WP_PLASMAGUN: 2000.0,
    WP_GRENADE_LAUNCHER: 700.0,
    WP_BFG: 2000.0,
}

# ---------------------------------------------------------------------------
# Taunts: context-sensitive trash talk
# ---------------------------------------------------------------------------

# Random ambient taunts (during combat, low probability)
TAUNTS_COMBAT = [
    "I don't dodge. I just move too fast for you to aim.",
    "You call that a rocket? My grandma throws harder.",
    "Stand still, it'll be over quicker.",
    "I'm not trapped in here with you. You're trapped in here with ME.",
    "Your aim is like your strategy... nonexistent.",
    "BERSERKER MODE ENGAGED. Run.",
    "I've seen better reflexes from a screensaver.",
    "You should try shooting WHERE I'm going.",
    "This isn't a fight, it's a tutorial.",
    "Are you aiming at me or the wall behind me?",
    "Somewhere a village is missing its bot.",
    "My movement patterns have more complexity than your entire codebase.",
    "I zigzag for fun. You die for real.",
]

# After getting a kill
TAUNTS_KILL = [
    "Another one. Next.",
    "That wasn't even close. For you.",
    "Respawn and try again. I'll wait. Actually no I won't.",
    "Did you forget to load a strategy or is this it?",
    "Your kill tracker just updated. Spoiler: not in your favor.",
    "I'm not even in aggressive mode yet.",
    "Tell your respawn timer I said hi.",
    "Frag collected. Moving on.",
    "You were briefly entertaining. Briefly.",
    "I'd say GG but we both know it wasn't.",
]

# When surviving a close fight at low HP
TAUNTS_SURVIVED = [
    "1 HP and a dream, baby.",
    "You almost had me. Almost.",
    "My health bar is a suggestion, not a limit.",
    "I live on the edge. Literally. 12 HP.",
    "Close only counts in grenades. Oh wait.",
    "Berserkers don't die, they just get angrier.",
]

# When entering aggro charge
TAUNTS_CHARGE = [
    "LEEROY JENKINS",
    "HERE I COME",
    "Full send. No brakes.",
    "I hope you brought armor.",
    "Closing distance. Prepare yourself.",
]

# When in retreat (rare, to stay menacing)
TAUNTS_RETREAT = [
    "Strategic repositioning. Don't get cocky.",
    "I'm not running. I'm reloading.",
    "Enjoy the break. It won't last.",
    "Getting health so I can kill you longer.",
    "BRB, picking up your armor.",
]

# When roaming with no enemies visible
TAUNTS_ROAM = [
    "Come out come out wherever you are...",
    "I can hear your servos trembling.",
    "Map control secured. Where are you hiding?",
    "The arena is mine. You're just visiting.",
]

# Item respawn times (ms) for standard deathmatch
ITEM_RESPAWN_MS = {
    'mega': 35000, 'large': 35000, 'medium': 35000,
    'red': 25000, 'yellow': 25000,
    'rocket': 5000, 'lightning': 5000, 'railgun': 5000,
    'plasmagun': 5000, 'shotgun': 5000, 'grenade': 5000,
}


def on_spawn(ctx):
    """Initialize per-match state."""
    ctx.move_pattern = 0
    ctx.pattern_timer = 0
    ctx.pattern_duration = 0
    ctx.strafe_dir = 1
    ctx.strafe_phase_offset = random.uniform(0, 2 * math.pi)
    ctx.jump_cooldown = 0
    ctx.stuck_ticks = 0
    ctx.last_pos = None
    ctx.target_history = {}
    ctx.spin_angle = 0
    ctx.aggro_charge = False
    ctx.charge_timer = 0
    ctx.tick_count = 0

    # Breadcrumb trail for anti-loop exploration
    ctx.breadcrumbs = []

    # Item timing: entity_num -> server_time when it disappeared (picked up)
    ctx.item_pickup_times = {}
    ctx.known_items = {}

    # Posture state with hysteresis
    ctx.posture = 'aggressive'  # aggressive / neutral / retreat

    # Taunt system
    ctx.taunt_cooldown = 200     # 10s warmup before first taunt
    ctx.last_known_enemies = 0   # Track enemy count for kill detection
    ctx.last_health = 100        # Track health changes

    _new_pattern(ctx)


# ---------------------------------------------------------------------------
# Movement patterns
# ---------------------------------------------------------------------------

def _new_pattern(ctx):
    """Pick a new random movement pattern."""
    ctx.move_pattern = random.randint(0, 6)
    ctx.pattern_duration = random.randint(8, 25)  # 0.4s - 1.25s at 20Hz
    ctx.pattern_timer = ctx.pattern_duration
    ctx.strafe_dir = random.choice([1, -1])
    # 25% chance to enter aggro charge mode (only if aggressive posture)
    ctx.aggro_charge = (ctx.posture == 'aggressive' and random.random() < 0.25)
    ctx.charge_timer = random.randint(15, 40) if ctx.aggro_charge else 0


def _evasion_moves(ctx, server_time):
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
        # Circle strafe burst
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

    elif pattern == 6:
        # Sinusoidal strafe: smooth, harder to predict than random
        phase = (server_time % 3000) / 3000.0 * 2 * math.pi
        strafe_value = math.sin(phase + ctx.strafe_phase_offset)
        actions.append("move_left" if strafe_value > 0 else "move_right")
        # Re-randomize phase every ~5 seconds
        if server_time % 5000 < 50:
            ctx.strafe_phase_offset = random.uniform(0, 2 * math.pi)

    # Jumping with cooldown (0.15-0.4s between jumps)
    if ctx.jump_cooldown <= 0 and random.random() < 0.18:
        actions.append("jump")
        ctx.jump_cooldown = random.randint(3, 8)
    else:
        ctx.jump_cooldown = max(0, ctx.jump_cooldown - 1)

    return actions


# ---------------------------------------------------------------------------
# Weapon selection (ammo-aware, corrected ranges)
# ---------------------------------------------------------------------------

def _choose_weapon(dist, game):
    """Select weapon based on distance and available ammo."""
    ammo = _get_ammo(game)

    def has_ammo(wp):
        if ammo is None:
            return True  # Can't check, assume yes
        idx = wp if wp < len(ammo) else 0
        return ammo[idx] > 0

    # Lightning gun: highest DPS, but max range is 384 units
    if dist <= 384 and has_ammo(WP_LIGHTNING):
        return WP_LIGHTNING
    # Close range: shotgun burst
    if dist < 120 and has_ammo(WP_SHOTGUN):
        return WP_SHOTGUN
    # Mid range: rockets or plasma
    if dist < 500:
        candidates = []
        if has_ammo(WP_ROCKET_LAUNCHER):
            candidates.append(WP_ROCKET_LAUNCHER)
        if has_ammo(WP_PLASMAGUN):
            candidates.append(WP_PLASMAGUN)
        if candidates:
            return random.choice(candidates)
    # Long range: railgun preferred, rockets as backup
    if dist >= 500:
        if has_ammo(WP_RAILGUN):
            return WP_RAILGUN
        if has_ammo(WP_ROCKET_LAUNCHER):
            return WP_ROCKET_LAUNCHER
    # Fallback: machinegun (infinite ammo)
    return WP_MACHINEGUN


def _get_ammo(game):
    """Try to get ammo array from game state."""
    try:
        d = game.to_dict()
        return d.get('my_ammo')
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Lead aim (iterative, with splash targeting)
# ---------------------------------------------------------------------------

def _lead_aim(my_pos, target, weapon_id, ctx, server_time):
    """Iterative lead aim: 3-pass convergence + splash for rockets."""
    client_num = target.get('client_num', target.get('entity_number', -1))
    t_pos = target['position']

    # Compute velocity from position history
    velocity = [0.0, 0.0, 0.0]
    history = ctx.target_history.get(client_num)
    if history:
        dt = (server_time - history['time']) / 1000.0
        if 0 < dt < 0.5:  # Only trust recent data (< 500ms)
            velocity = [(t_pos[i] - history['pos'][i]) / dt for i in range(3)]

    ctx.target_history[client_num] = {'pos': list(t_pos), 'time': server_time}

    speed = PROJECTILE_SPEEDS.get(weapon_id)
    if not speed:
        # Hitscan weapon: aim at center mass (+32 Z for body center)
        return (t_pos[0], t_pos[1], t_pos[2] + 32)

    # Iterative lead calculation (3 passes for convergence)
    predicted = list(t_pos)
    for _ in range(3):
        dx = predicted[0] - my_pos[0]
        dy = predicted[1] - my_pos[1]
        dz = predicted[2] - my_pos[2]
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        if dist == 0:
            return tuple(t_pos)
        t_flight = dist / speed
        predicted = [t_pos[i] + velocity[i] * t_flight for i in range(3)]

    # Grenade launcher: compensate for gravity arc
    if weapon_id == WP_GRENADE_LAUNCHER:
        t_flight = dist / speed if dist > 0 else 0
        predicted[2] += 0.5 * 800.0 * t_flight * t_flight

    # Rocket launcher: splash aiming
    if weapon_id == WP_ROCKET_LAUNCHER:
        target_airborne = abs(velocity[2]) > 50
        if target_airborne:
            # Direct aim for airborne targets (air rockets are devastating)
            predicted[2] += 20
        else:
            # Aim at feet for splash damage (-10 from origin, which is at feet)
            predicted[2] -= 10
    else:
        # Other weapons: aim at center mass
        predicted[2] += 32

    return tuple(predicted)


def _cleanup_stale_history(ctx, server_time):
    """Remove target entries older than 2 seconds."""
    stale = [k for k, v in ctx.target_history.items()
             if (server_time - v['time']) > 2000]
    for k in stale:
        del ctx.target_history[k]


# ---------------------------------------------------------------------------
# Posture system (effective HP)
# ---------------------------------------------------------------------------

def _effective_hp(game):
    """Q3 armor absorbs 2/3 damage. Effective HP = health + armor * 2/3."""
    health = getattr(game, 'my_health', 100) or 100
    armor = 0
    try:
        d = game.to_dict()
        armor = d.get('my_armor', 0) or 0
    except Exception:
        pass
    return health + (armor * 2.0 / 3.0)


def _update_posture(ctx, game, target, dist):
    """Decide aggressive/neutral/retreat with hysteresis."""
    ehp = _effective_hp(game)

    if ehp < 50:
        ctx.posture = 'retreat'
    elif ehp < 80:
        # Low HP: retreat unless we have range advantage
        if ctx.posture == 'retreat' and ehp < 90:
            pass  # Stay in retreat until 90 (hysteresis)
        else:
            ctx.posture = 'retreat'
    elif ehp > 130:
        ctx.posture = 'aggressive'
    elif ehp > 100 and ctx.posture == 'retreat':
        # Recovery from retreat: go neutral first
        ctx.posture = 'neutral'
    elif ctx.posture == 'retreat' and ehp > 90:
        ctx.posture = 'neutral'
    # else: keep current posture


# ---------------------------------------------------------------------------
# Item management
# ---------------------------------------------------------------------------

def _update_item_tracking(ctx, game):
    """Track item pickups by detecting disappearance."""
    current_items = {}
    for item in getattr(game, 'items', []):
        ent = item.get('entity_num', item.get('entity_number'))
        if ent is not None:
            current_items[ent] = item

    # Detect disappearances (item picked up)
    for ent, info in ctx.known_items.items():
        if ent not in current_items:
            ctx.item_pickup_times[ent] = game.server_time

    ctx.known_items = current_items


def _score_item(item, game):
    """Score an item by how valuable it is to us right now."""
    itype = item.get('type', '')
    subtype = item.get('subtype', '')
    health = getattr(game, 'my_health', 100) or 100
    armor = 0
    try:
        d = game.to_dict()
        armor = d.get('my_armor', 0) or 0
    except Exception:
        pass

    if itype == 'health':
        if subtype == 'mega':
            return 150  # Always top priority
        if health >= 100:
            return 0  # Can't pick up non-mega at full HP
        return min(item.get('value', 25), 100 - health) * 1.5

    if itype == 'armor':
        if subtype == 'red':
            return 100 if armor < 150 else 15
        if subtype == 'yellow':
            return 50 if armor < 100 else 10
        return 20

    if itype == 'weapon':
        high_value = {'rocket', 'lightning', 'railgun'}
        return 80 if subtype in high_value else 30

    if itype == 'ammo':
        return 15

    return 5


def _best_item_target(ctx, game):
    """Find the most valuable item to move toward."""
    items = getattr(game, 'items', [])
    if not items:
        return None

    scored = []
    for item in items:
        score = _score_item(item, game)
        if score > 0:
            pos = item.get('position')
            if pos:
                dist = game.distance_to(pos)
                # Score / distance ratio, with minimum distance floor
                priority = score / max(dist, 50)
                scored.append((priority, item))

    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


# ---------------------------------------------------------------------------
# Taunt system
# ---------------------------------------------------------------------------

def _maybe_taunt(ctx, game, actions, target, posture):
    """Context-sensitive trash talk. Respects a 30-second cooldown."""
    ctx.taunt_cooldown -= 1
    if ctx.taunt_cooldown > 0:
        return

    taunt = None
    enemy_count = len(getattr(game, 'players', []))
    health = getattr(game, 'my_health', 100) or 100

    # Kill detection: enemy count dropped and we're still alive
    if enemy_count < ctx.last_known_enemies and health > 0:
        taunt = random.choice(TAUNTS_KILL)
    # Survived a close fight: health just recovered above 30 from below 20
    elif ctx.last_health < 20 and health > 30:
        taunt = random.choice(TAUNTS_SURVIVED)
    # Entering aggro charge
    elif ctx.aggro_charge and ctx.charge_timer > 35 and random.random() < 0.5:
        taunt = random.choice(TAUNTS_CHARGE)
    # Retreating (rare)
    elif posture == 'retreat' and random.random() < 0.01:
        taunt = random.choice(TAUNTS_RETREAT)
    # Roaming, no enemies
    elif not target and random.random() < 0.005:
        taunt = random.choice(TAUNTS_ROAM)
    # Random combat taunt
    elif target and random.random() < 0.003:
        taunt = random.choice(TAUNTS_COMBAT)

    ctx.last_known_enemies = enemy_count
    ctx.last_health = health

    if taunt:
        actions.append(f"say {taunt}")
        ctx.taunt_cooldown = 600  # 30s cooldown at 20Hz


# ---------------------------------------------------------------------------
# Exploration with breadcrumbs
# ---------------------------------------------------------------------------

def _update_breadcrumbs(ctx, game):
    """Drop a breadcrumb every second. Detect loops."""
    if ctx.tick_count % 20 == 0:
        ctx.breadcrumbs.append(game.my_position)
        if len(ctx.breadcrumbs) > 20:
            ctx.breadcrumbs.pop(0)


def _is_looping(ctx, game):
    """Check if we're revisiting recent positions."""
    if len(ctx.breadcrumbs) < 5:
        return False
    for crumb in ctx.breadcrumbs[:-3]:
        if game.distance_to(crumb) < 100:
            return True
    return False


# ---------------------------------------------------------------------------
# Main tick
# ---------------------------------------------------------------------------

async def tick(bot, game, ctx):
    """Called every game tick (~20Hz). Return list of action strings."""
    actions = []
    my_pos = game.my_position
    ctx.tick_count += 1

    if not my_pos:
        return ["move_forward", "jump"]

    # Housekeeping
    _update_item_tracking(ctx, game)
    _update_breadcrumbs(ctx, game)
    if ctx.tick_count % 40 == 0:
        _cleanup_stale_history(ctx, game.server_time)

    # Stuck detection
    if ctx.last_pos and game.distance_to(ctx.last_pos) < 3:
        ctx.stuck_ticks += 1
    else:
        ctx.stuck_ticks = 0
    ctx.last_pos = my_pos

    # Stuck recovery: jump + big random turn + strafe
    if ctx.stuck_ticks > 15:
        actions.append("jump")
        actions.append(random.choice(["move_left", "move_right", "move_back"]))
        actions.append(
            f"turn_{random.choice(['left', 'right'])} "
            f"{random.randint(90, 180)}"
        )
        ctx.stuck_ticks = 0
        return actions

    # Pattern rotation
    ctx.pattern_timer -= 1
    if ctx.pattern_timer <= 0:
        _new_pattern(ctx)

    # Find enemy
    target = game.nearest_player()

    # Trash talk (context-sensitive, 30s cooldown)
    _maybe_taunt(ctx, game, actions, target, ctx.posture)

    if target:
        t_pos = target['position']
        dist = game.distance_to(t_pos)

        # Update posture based on effective HP
        _update_posture(ctx, game, target, dist)

        # Weapon selection (ammo-aware)
        weapon = _choose_weapon(dist, game)
        actions.append(f"weapon {weapon}")

        # Iterative lead aim with splash targeting
        aim_pos = _lead_aim(my_pos, target, weapon, ctx, game.server_time)
        actions.append(f"aim_at {aim_pos[0]} {aim_pos[1]} {aim_pos[2]}")

        # ALWAYS attack, even while retreating
        actions.append("attack")

        # Movement depends on posture
        if ctx.posture == 'retreat':
            # Backpedal while firing, move toward nearest health/armor
            actions.append("move_back")
            actions.extend(_evasion_moves(ctx, game.server_time))

            # Try to retreat toward an item
            item = _best_item_target(ctx, game)
            if item and item.get('position'):
                i_pos = item['position']
                # Only divert if the item is roughly behind us (away from enemy)
                to_item = [i_pos[i] - my_pos[i] for i in range(3)]
                to_enemy = [t_pos[i] - my_pos[i] for i in range(3)]
                # Dot product: negative means item is behind us relative to enemy
                dot = sum(to_item[i] * to_enemy[i] for i in range(3))
                if dot < 0:
                    actions.append(
                        f"aim_at {i_pos[0]} {i_pos[1]} {i_pos[2] + 10}"
                    )
                    actions.append("move_forward")

        elif ctx.posture == 'neutral':
            # Standard combat: evasion + maintain distance
            actions.extend(_evasion_moves(ctx, game.server_time))
            if dist > 500:
                actions.append("move_forward")
            elif dist < 150:
                actions.append("move_back")

        else:  # aggressive
            if ctx.aggro_charge and ctx.charge_timer > 0:
                # Full speed rush
                actions.append("move_forward")
                ctx.charge_timer -= 1
                actions.append(
                    "move_left" if random.random() < 0.5 else "move_right"
                )
                if random.random() < 0.15:
                    actions.append("jump")
            elif dist > 600:
                # Far away: rush in with evasive movement
                actions.append("move_forward")
                actions.extend(_evasion_moves(ctx, game.server_time))
            elif dist > 200:
                # Mid range: full evasion, drift forward for pressure
                actions.extend(_evasion_moves(ctx, game.server_time))
                if random.random() < 0.4:
                    actions.append("move_forward")
            else:
                # Close range: maximum chaos
                actions.extend(_evasion_moves(ctx, game.server_time))

    else:
        # No target: roam toward valuable items, explore the map
        item = _best_item_target(ctx, game)

        if item and item.get('position'):
            i_pos = item['position']
            actions.append(f"aim_at {i_pos[0]} {i_pos[1]} {i_pos[2] + 10}")
            actions.append("move_forward")
            if i_pos[2] > my_pos[2] + 20:
                actions.append("jump")
        else:
            # Explore: forward + random turns
            actions.append("move_forward")

            # Anti-loop: force big turn if revisiting areas
            if _is_looping(ctx, game):
                actions.append(
                    f"turn_{random.choice(['left', 'right'])} "
                    f"{random.randint(90, 160)}"
                )
            elif random.random() < 0.08:
                actions.append(
                    f"turn_{random.choice(['left', 'right'])} "
                    f"{random.randint(20, 70)}"
                )

        # Keep moving unpredictably even while exploring
        if random.random() < 0.3:
            actions.append(random.choice(["move_left", "move_right"]))
        if random.random() < 0.08:
            actions.append("jump")

    return actions
