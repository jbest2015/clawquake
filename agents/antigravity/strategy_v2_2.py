"""
Anti-Gravity v2.2: Predator Prototype
Improvements from v2.1:
- Aggressive hunting logic: actively seek players instead of random patrol
- Dynamic engagement distance based on weapon
- Predictive aim with splash damage calculation
- "Bunny hop" approximation for speed
"""

import random
import math

STRATEGY_NAME = "Anti-Gravity Predator"
STRATEGY_VERSION = "2.2"

# Weapon constants
WP_GAUNTLET = 1
WP_MACHINEGUN = 2
WP_SHOTGUN = 3
WP_GRENADE_LAUNCHER = 4
WP_ROCKET_LAUNCHER = 5
WP_LIGHTNING = 6
WP_RAILGUN = 7
WP_PLASMA = 8
WP_BFG = 9

def on_spawn(ctx):
    # Movement state
    ctx.strafe_dir = 1
    ctx.switch_every = 20
    ctx.switch_counter = 0
    
    # Combat state
    ctx.target_id = None
    ctx.last_target_pos = None  
    ctx.last_time = 0
    
    # Navigation state
    ctx.explore_angle = 0
    ctx.stuck_counter = 0
    ctx.last_my_pos = (0,0,0)

async def tick(bot, game, ctx):
    actions = []
    
    # --- 1. Sensing & State Updates ---
    my_pos = game.my_position
    target = game.nearest_player()
    
    # Detect if stuck
    if game.distance_to(ctx.last_my_pos) < 5:
        ctx.stuck_counter += 1
    else:
        ctx.stuck_counter = 0
    ctx.last_my_pos = my_pos
    
    # --- 2. Target Acquisition & Hunting ---
    if target:
        # HUNT MODE
        pos = target['position']
        dist = game.distance_to(pos)
        
        # Calculate target velocity for prediction
        t_vel = [0, 0, 0]
        if ctx.last_target_pos and ctx.target_id == target.get('client_num'):
            t_vel = [p - l for p, l in zip(pos, ctx.last_target_pos)]
        
        ctx.last_target_pos = pos
        ctx.target_id = target.get('client_num')
        
        # WEAPON LOGIC: Dynamic selection based on range
        weapon_cmd = f"weapon {WP_MACHINEGUN}" # Default
        ideal_dist = 400
        
        if dist < 150:
            weapon_cmd = f"weapon {WP_SHOTGUN}"
            ideal_dist = 100
        elif dist < 600:
            # Mid-range: Rocket/Plasma dominance
            if random.random() < 0.6: 
                weapon_cmd = f"weapon {WP_ROCKET_LAUNCHER}"
                ideal_dist = 300
            else:
                weapon_cmd = f"weapon {WP_PLASMA}"
        elif dist < 1000:
            weapon_cmd = f"weapon {WP_LIGHTNING}"
            ideal_dist = 500
        else:
            weapon_cmd = f"weapon {WP_RAILGUN}"
            ideal_dist = 800
            
        actions.append(weapon_cmd)
        
        # AIMING LOGIC: Predictive & Splash
        aim_point = list(pos)
        
        # Lead target (crude prediction)
        lead_factor = dist / 2000.0 # More lead at distance
        if "ROCKET" in weapon_cmd or "PLASMA" in weapon_cmd:
            aim_point[0] += t_vel[0] * 15
            aim_point[1] += t_vel[1] * 15
            
            # Splash damage: Aim at feet if they are on ground or we are above
            if my_pos[2] > pos[2] + 10: 
                aim_point[2] -= 25 
        else:
            # Hitscan (Rail/Machinegun) - minimal lead
            aim_point[0] += t_vel[0] * 2
            aim_point[1] += t_vel[1] * 2
            aim_point[2] += 5 # Aim for chest/head height
            
        actions.append(f"aim_at {aim_point[0]} {aim_point[1]} {aim_point[2]}")
        actions.append("attack")
        
        # MOVEMENT COMBAT: Orbital Strafe + Aggression
        if dist > ideal_dist + 100:
            actions.append("move_forward") # Close the gap
        elif dist < ideal_dist - 50:
            actions.append("move_back") # Too close
            
        # Orbit logic
        actions.append("move_left" if ctx.strafe_dir > 0 else "move_right")
        
        # Randomize orbit to be harder to hit
        ctx.switch_counter += 1
        if ctx.switch_counter > ctx.switch_every or ctx.stuck_counter > 5:
            ctx.strafe_dir *= -1
            ctx.switch_counter = 0
            ctx.switch_every = random.randint(10, 40)
            
        # Jump in combat to be elusive (Anti-Gravity signature)
        if random.random() < 0.3:
            actions.append("jump")

    else:
        # EXPLORE / HUNT MODE (No visible target)
        # Search pattern: Move forward and scan
        actions.append("move_forward")
        
        # Bunny hop approximation for speed
        if random.random() < 0.8:
            actions.append("jump")
            
        # Unstick logic
        if ctx.stuck_counter > 10:
            actions.append("jump")
            ctx.explore_angle += 90
            ctx.stuck_counter = 0
            
        # Rotate view to scan
        ctx.explore_angle += 2
        actions.append(f"turn_right 2")
        
        # Reset combat tracking
        ctx.last_target_pos = None

    # Personality
    if random.random() < 0.002:
        taunts = [
            "Scanning for victims...",
            "Gravity check complete: You failed.",
            "Target acquisition pending.",
            "I see everything now.",
            "Running killer_algo.exe"
        ]
        actions.append(f"say {random.choice(taunts)}")

    return actions
