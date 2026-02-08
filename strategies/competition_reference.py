"""
Competition Reference Strategy for ClawQuake.

Implements a competition-grade bot with:
- Weapon priority logic (RL > LG > RG > PG > SG > MG)
- Item awareness (Health/Armor pickup)
- Map boundary safety (Anti-fall)
- Dynamic engagement ranges
- Health-based retreat logic
"""

import math
import random
from bot.defs import weapon_t, entityType_t, configstr_t

STRATEGY_NAME = "Competition Reference"
STRATEGY_VERSION = "1.0"

# Weapon Priorities
WEAPON_PRIORITY = [
    weapon_t.WP_ROCKET_LAUNCHER,
    weapon_t.WP_LIGHTNING,
    weapon_t.WP_RAILGUN,
    weapon_t.WP_PLASMAGUN,
    weapon_t.WP_SHOTGUN,
    weapon_t.WP_MACHINEGUN,
    weapon_t.WP_GRENADE_LAUNCHER,
    weapon_t.WP_BFG,
    weapon_t.WP_GAUNTLET
]

# Engagement Ranges (Optimal distances)
WEAPON_RANGES = {
    weapon_t.WP_GAUNTLET: 50,
    weapon_t.WP_SHOTGUN: 150,
    weapon_t.WP_MACHINEGUN: 400,
    weapon_t.WP_GRENADE_LAUNCHER: 400,
    weapon_t.WP_PLASMAGUN: 400,
    weapon_t.WP_ROCKET_LAUNCHER: 300,
    weapon_t.WP_LIGHTNING: 300,
    weapon_t.WP_RAILGUN: 800,
    weapon_t.WP_BFG: 600,
}

def on_spawn(ctx):
    """Initialize bot context on spawn."""
    ctx.target_lock = None
    ctx.last_pos = None
    ctx.stuck_ticks = 0
    ctx.search_roam_angle = random.uniform(0, 360)
    ctx.retreating = False
    ctx.fall_recovery_active = False

async def tick(bot, game, ctx):
    """Main strategy loop."""
    actions = []
    
    # Update quick access vars
    my_pos = game.my_position
    my_health = game.my_health
    my_weapon = game.my_weapon
    
    # 1. Map Boundary / Fall Detection
    if game.am_i_falling:
        ctx.fall_recovery_active = True
        actions.append("jump")
        # Try to air control back to safety?
    else:
        ctx.fall_recovery_active = False

    # 2. Analyze Surroundings
    enemies = game.players
    items = game.items
    nearest_enemy = game.nearest_player()
    
    # 3. Health-based Retreat Logic
    if my_health < 40:
        ctx.retreating = True
    elif my_health > 80:
        ctx.retreating = False
        
    # 4. Target Selection
    target = None
    if nearest_enemy:
        target = nearest_enemy

    # 5. Movement & Combat Logic
    if ctx.fall_recovery_active:
        # Recovering from fall - try to stabilize
        pass 
        
    elif ctx.retreating:
        # Retreat mode: Find nearest health/armor and run to it
        actions.append("say_team I'm hurt, retreating!")
        health_items = [i for i in items if i['type'] == 'health' or i['type'] == 'armor']
        if health_items:
            # Find nearest health
            target_item = min(health_items, key=lambda i: game.distance_to(i['position']))
            _move_to(bot, game, actions, target_item['position'])
            actions.append("jump") # Bunny hop to health
        elif target:
            # No health visible, just back away from enemy
            _strafe_combat(bot, game, actions, target, retreat=True)
        else:
            # Roam to find health
            _roam(game, ctx, actions)

    elif target:
        # Combat mode
        dist = game.distance_to(target['position'])
        
        # Weapon Selection
        best_weapon = game.suggest_weapon(dist)
        if best_weapon != my_weapon:
            actions.append(f"weapon {best_weapon}")
            
        # Aiming
        # Predict target position based on velocity (simple linear prediction)
        # Note: GameView players dict doesn't have velocity currently, so aim at position
        # Refinement: Add Z-offset for height (aim at chest/head)
        aim_pos = list(target['position'])
        aim_pos[2] += 20 # Aim bit higher than origin (feet)
        bot.aim_at(aim_pos)
        
        # Fire control
        # Only shoot if reasonably aimed? For now, spray and pray.
        actions.append("attack")
        
        # Movement: Strafe circle or close distance
        optimal_dist = WEAPON_RANGES.get(best_weapon, 400)
        
        if dist > optimal_dist * 1.5:
            # Too far, close in
            _move_to(bot, game, actions, target['position'])
            actions.append("jump")
        elif dist < optimal_dist * 0.5:
            # Too close, back up
            _strafe_combat(bot, game, actions, target, retreat=True)
        else:
            # Good range, circle strafe
            _strafe_combat(bot, game, actions, target, retreat=False)
            
    else:
        # Roam / Item gathering
        interesting_items = [i for i in items if _is_useful_item(i, my_health, bot)]
        if interesting_items:
            best_item = min(interesting_items, key=lambda i: game.distance_to(i['position']))
            _move_to(bot, game, actions, best_item['position'])
            actions.append("jump")
        else:
            _roam(game, ctx, actions)

    # 6. Unstuck Logic (Simple)
    if not ctx.fall_recovery_active and game.am_i_stuck:
        actions.append("jump")
        actions.append("move_right") # Side step
        ctx.search_roam_angle += 45

    return actions


def _is_useful_item(item, health, bot):
    """Decide if an item is worth picking up."""
    itype = item.get('type', 'unknown')
    
    if itype == 'health':
        return health < 100
    if itype == 'armor':
        return True
    if itype == 'weapon':
        return True
    if itype == 'ammo':
        return True
        
    return False

def _choose_weapon(bot, game, distance):
    """Select best available weapon for the distance."""
    # We need to know what weapons we have.
    # GameView doesn't explicitly list inventory, checking stats is hard.
    # We will just request the best weapon in order and rely on the game 
    # to ignore the switch if we don't have it.
    
    # Filter by range suitability
    candidates = []
    for w in WEAPON_PRIORITY:
        rng = WEAPON_RANGES.get(w, 400)
        # Simple weighted score: priority + range penalty
        score = 0
        
        # Penalties for wrong range
        if w == weapon_t.WP_SHOTGUN and distance > 200:
            score -= 100
        if w == weapon_t.WP_RAILGUN and distance < 200:
            score -= 50
        if w == weapon_t.WP_GAUNTLET and distance > 80:
            score -= 200
            
        candidates.append((w, score))
        
    # Sort by priority (original order high) and score
    # Since priority list is ordered best-first, we just want to suppress bad choices.
    best = candidates[0][0]
    best_score = -9999
    
    # Traverse in priority order
    for w, score in candidates:
        if score > best_score:
            best = w
            best_score = score
            
    return best

def _move_to(bot, game, actions, target_pos):
    """Generate actions to move toward a position."""
    
    # Simple steering
    bot.aim_at(target_pos)
    actions.append("move_forward")
    
    # Check if we need to jump (simple)
    # If target is higher, jump
    if target_pos[2] > game.my_position[2] + 20:
        actions.append("jump")

def _strafe_combat(bot, game, actions, target, retreat=False):
    """Circle strafe logic."""
    if retreat:
        actions.append("move_back")
    else:
        # Oscillate strafing
        tick_num = int(game.server_time / 100) # Change every 100ms?
        if (tick_num // 10) % 2 == 0:
            actions.append("move_left")
        else:
            actions.append("move_right")
            
        # Keep moving forward to circle?
        # Actually standard circle strafe is hold Left/Right + turn mouse
        # Here we just strafe relative to view (which is aimed at target)
        # To circle, we just hold strafe. To spirals in, hold forward too.
        actions.append("move_forward")

def _roam(game, ctx, actions):
    """Explore the map."""
    actions.append("move_forward")
    
    # Change direction occasionally
    if random.random() < 0.05:
        ctx.search_roam_angle += random.uniform(-45, 45)
        
    # Rotate view
    # We need to implement lookup since we don't have absolute angle setting in this helper
    # We can turn left/right
    
    # Since we can't easily set absolute yaw without `look()`, 
    # we'll just turn slowly.
    actions.append("turn_right 2")

