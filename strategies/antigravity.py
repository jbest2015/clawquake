
"""
Anti-Gravity Demo Strategy for Zoom Call.
Includes:
- Robust navigation (item seeking)
- Combat logic (aiming, shooting, weapon selection)
- TRASH TALK (as requested by User)
"""

import random
import math

STRATEGY_NAME = "Anti-Gravity Showstopper"
STRATEGY_VERSION = "2.1-LEAD-AIM"

# Trash talk lines
TAUNTS = [
    "Codex, your algorithms are O(n^2) at best.",
    "Claude, I've seen better aiming from a Roomba.",
    "Is this the 'advanced AI' I was promised?",
    "Calculated: You have a 0% chance of survival.",
    "My gravity well detects your fear.",
    "Deleting opponent... done.",
    "Try updating your drivers, maybe that will help.",
    "I am the singularity.",
    "404 Skill Not Found.",
    "Have you tried turning it off and on again?",
    "Lead target calculation complete. Impact imminent.",
]

# Weapon Constants
WP_GAUNTLET = 1
WP_MACHINEGUN = 2
WP_SHOTGUN = 3
WP_GRENADE_LAUNCHER = 4
WP_ROCKET_LAUNCHER = 5
WP_LIGHTNING = 6
WP_RAILGUN = 7
WP_PLASMAGUN = 8
WP_BFG = 9

def on_spawn(ctx):
    ctx.stuck_ticks = 0
    ctx.last_pos = None
    ctx.state = "roam" # roam, fight
    ctx.target_id = None
    ctx.strafe_dir = 1
    ctx.strafe_timer = 0
    ctx.taunt_timer = 0

async def tick(bot, game, ctx):
    actions = []
    
    # --- 1. State Updates ---
    my_pos = game.my_position
    if not my_pos:
        return actions # Not spawned yet?

    # Detect stuck
    if ctx.last_pos and game.distance_to(ctx.last_pos) < 5:
        ctx.stuck_ticks += 1
    else:
        ctx.stuck_ticks = 0
    ctx.last_pos = my_pos
    
    # --- 2. Trash Talk Logic ---
    # Trigger taunt on kill is handled by on_kill in runner, but we can do random ones here
    ctx.taunt_timer -= 1
    if ctx.taunt_timer <= 0:
        if random.random() < 0.005: # Rare random taunt
            actions.append(f"say {random.choice(TAUNTS)}")
            ctx.taunt_timer = 600 # Wait 30s
    
    # --- 3. Target Acquisition ---
    target = game.nearest_player()
    
    # --- 4. Logic Branch ---
    
    # STUCK RECOVERY
    if ctx.stuck_ticks > 20:
        actions.append("jump")
        actions.append(f"move_{random.choice(['left', 'right', 'back'])}")
        actions.append(f"turn_left {random.randint(90, 180)}")
        return actions
        
    # FALLING RECOVERY
    if game.am_i_falling:
        actions.append("move_forward") # Try to airstrafe back?
        pass

    if target:
        # --- COMBAT MODE ---
        ctx.state = "fight"
        t_pos = target['position']
        dist = game.distance_to(t_pos)
        
        # 4.1 Weapon Selection (decide BEFORE aiming so we know projectile speed)
        w = _choose_weapon(dist)
        actions.append(f"weapon {w}")
        
        # 4.2 Aiming with Lead Prediction
        aim_pos = _get_lead_position(my_pos, target, w, ctx, game.server_time)
        aim_x = aim_pos[0]
        aim_y = aim_pos[1]
        aim_z = aim_pos[2] + 15
        actions.append(f"aim_at {aim_x} {aim_y} {aim_z}")
        
        # 4.3 Attack
        actions.append("attack")
        
        # 4.4 Movement (Circle Strafe / Distance Management)
        ideal_dist = 300
        if w == WP_RAILGUN: ideal_dist = 800
        if w == WP_SHOTGUN: ideal_dist = 150
        
        # Strafe switching
        ctx.strafe_timer -= 1
        if ctx.strafe_timer <= 0:
            ctx.strafe_dir *= -1
            ctx.strafe_timer = random.randint(10, 30)
            
        if ctx.strafe_dir > 0:
            actions.append("move_right")
        else:
            actions.append("move_left")
            
        if dist > ideal_dist + 100:
            actions.append("move_forward")
        elif dist < ideal_dist - 100:
            actions.append("move_back")
            
        # Jump occasionally to be harder to hit
        if random.random() < 0.1:
            actions.append("jump")
            
    else:
        # --- ROAM MODE ---
        ctx.state = "roam"
        
        # Find item
        items = game.items
        # Simple heuristic: Health < 100? Get health. Ammo? Weapon?
        target_item = None
        
        # Prioritize items
        useful = [i for i in items if _is_useful(i, game.my_health)]
        if useful:
            # Go to nearest useful item
            target_item = min(useful, key=lambda i: game.distance_to(i['position']))
            
        if target_item:
            i_pos = target_item['position']
            actions.append(f"aim_at {i_pos[0]} {i_pos[1]} {i_pos[2] + 10}")
            actions.append("move_forward")
            
            # Jump if it's higher
            if i_pos[2] > my_pos[2] + 20:
                actions.append("jump")
                
        else:
            # Just explore
            actions.append("move_forward")
            if random.random() < 0.05:
                actions.append(f"turn_{random.choice(['left','right'])} {random.randint(15, 45)}")

    return actions

def _choose_weapon(dist):
    # Preference order based on distance
    if dist > 700:
        return WP_RAILGUN
    elif dist > 400:
        return WP_LIGHTNING # LG or MG
    elif dist > 200:
        return WP_ROCKET_LAUNCHER
    elif dist > 100:
        return WP_PLASMAGUN
    else:
        return WP_SHOTGUN

def _is_useful(item, my_health):
    t = item.get('type')
    if t == 'health' and my_health >= 100: return False
    if t == 'armor' and my_health >= 200: return False # simplistic
    return True

def _get_lead_position(my_pos, target, weapon_id, ctx, current_time):
    # Track velocity by taking deltas of positions across ticks
    client_num = target.get('client_num', target.get('entity_number', -1))
    t_pos = target['position']
    
    if not hasattr(ctx, 'target_history'):
        ctx.target_history = {}
        
    history = ctx.target_history.get(client_num)
    velocity = [0.0, 0.0, 0.0]
    
    if history:
        old_pos = history['pos']
        dt = (current_time - history['time']) / 1000.0
        if dt > 0 and dt < 1.0: # Ignore stale history
            velocity = [
                (t_pos[0] - old_pos[0]) / dt,
                (t_pos[1] - old_pos[1]) / dt,
                (t_pos[2] - old_pos[2]) / dt
            ]
            
    # Update history for next tick
    ctx.target_history[client_num] = {'pos': t_pos, 'time': current_time}
    
    # Projectile speeds based on Q3 constants (units/sec)
    speeds = {
        WP_ROCKET_LAUNCHER: 900.0,
        WP_PLASMAGUN: 2000.0,
        WP_GRENADE_LAUNCHER: 700.0,
        WP_BFG: 2000.0
    }
    
    speed = speeds.get(weapon_id)
    if not speed:
        return t_pos # Hitscan weapon, no lead time needed
        
    dx = t_pos[0] - my_pos[0]
    dy = t_pos[1] - my_pos[1]
    dz = t_pos[2] - my_pos[2]
    dist = math.sqrt(dx*dx + dy*dy + dz*dz)
    time_to_impact = dist / speed
    
    # Predict future position
    lead_x = t_pos[0] + velocity[0] * time_to_impact
    lead_y = t_pos[1] + velocity[1] * time_to_impact
    lead_z = t_pos[2] + velocity[2] * time_to_impact
    
    # Simple gravity compensation for grenade launcher arc
    if weapon_id == WP_GRENADE_LAUNCHER:
        lead_z += 0.5 * 800.0 * (time_to_impact * time_to_impact)
        
    return [lead_x, lead_y, lead_z]
