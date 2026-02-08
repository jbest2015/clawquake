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
    # If we are falling rapidly, try to airstrafe back or stop moving forward
    vel_z = game.my_velocity[2]
    if vel_z < -300: # Falling fast
        ctx.fall_recovery_active = True
        # Panic jump sometimes helps clip edges
        actions.append("jump")
        # Stop moving forward to avoid arcing further out
        # But if we were moving to a platform, maybe we should keep moving?
        # Safe bet: slight air control? For now, just don't push forward blindly.
    else:
        ctx.fall_recovery_active = False

    # 2. Analyze Surroundings (Items & Players)
    enemies = game.players
    items = _find_items(bot, game)
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
        health_items = [i for i in items if 'health' in i['name'] or 'armor' in i['name']]
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
        best_weapon = _choose_weapon(bot, game, dist)
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
    if not ctx.fall_recovery_active and _is_stuck(game, ctx):
        actions.append("jump")
        actions.append("move_right") # Side step
        ctx.search_roam_angle += 45

    return actions

def _find_items(bot, game):
    """Parse entities to find items."""
    items = []
    entities = game.entities
    if not entities:
        return items
        
    # Access config strings for item names
    # Note: parsing this properly depends on checking client config_strings
    # This is a bit advanced for the current API exposure, so we'll do best effort
    # if we can access the client.
    
    # We need the item list from config string CS_ITEMS (27)
    item_names = {}
    cs_items = bot.client.config_strings.get(configstr_t.CS_ITEMS)
    # This is usually a raw string, might need parsing context. 
    # Actually Q3 configstrings for items are usually scattered at 27, 28, etc?
    # No, CS_ITEMS is typically the start index?
    # In Q3 protocol 68/71, CS_ITEMS might be a single string or range.
    # OpenClaw client stores them in a dict.
    
    # Let's simplify: Iterate entities, check if eType == ET_ITEM
    for ent_num, ent in entities.items():
        if getattr(ent, 'eType', 0) == entityType_t.ET_ITEM:
             # Basic check. Without mapping modelindex to name, we can't be sure what it is.
             # However, we can guess or just treat all items as "good".
             items.append({
                 'entity_num': ent_num,
                 'position': ent.origin,
                 'name': 'unknown_item', # Placeholder
                 'modelindex': getattr(ent, 'modelindex', 0)
             })
             
             # Attempt to resolve name if possible
             # In standard Q3, item names are in config strings starting at 27?
             # Let's check if we can get the name from the bot client helper
             # (not currently implemented in client.py)
    
    # Map common model indices if possible (fallback)
    # This is unreliable across maps/mods, but better than nothing.
    
    # Retrieve item names from configstrings if available
    # Iterate CS_ITEMS onwards
    for i in range(configstr_t.CS_ITEMS, configstr_t.CS_ITEMS + 64): # Scan top 64 items
        val = bot.client.config_strings.get(i)
        if val:
            # Map items to modelindices?
            # Q3 item system is complex.
            # Simplified: Just grab matching items from string text
            # e.g. "item_armor_combat"
            
            # For this reference strategy, we will just assume any ET_ITEM is worth inspecting
            # and verify specific names if we find them.
            for item in items:
                if item['modelindex'] == (i - configstr_t.CS_ITEMS): # Rough guess of mapping
                     item['name'] = val
                     
    return items

def _is_useful_item(item, health, bot):
    """Decide if an item is worth picking up."""
    name = item.get('name', '').lower()
    
    if 'health' in name:
        return health < 100
    if 'armor' in name:
        return True # Always want armor
    if 'weapon' in name:
        return True # Always want weapons
    if 'ammo' in name:
        return True
        
    # If unknown, pick it up anyway
    return True

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

def _is_stuck(game, ctx):
    """Check if bot is stuck."""
    pos = game.my_position
    if ctx.last_pos:
        dx = pos[0] - ctx.last_pos[0]
        dy = pos[1] - ctx.last_pos[1]
        dist = math.sqrt(dx*dx + dy*dy)
        if dist < 5:
            ctx.stuck_ticks += 1
        else:
            ctx.stuck_ticks = 0
            
    ctx.last_pos = pos
    return ctx.stuck_ticks > 10
