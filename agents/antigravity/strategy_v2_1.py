"""
Anti-Gravity v2.1: Orbital Striker (Aggressive)
Improvements from v2.0:
- Tighter orbit distance (300 units)
- Higher jump frequency (90% chance)
- Faster orbit direction switching
- Extended weapon range for shotgun
"""

import random
import math

STRATEGY_NAME = "Anti-Gravity Orbital Striker"
STRATEGY_VERSION = "2.1"

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
    ctx.switch_every = 15
    ctx.switch_counter = 0
    ctx.ideal_distance = 300.0  # Very aggressive close range
    
    # Combat state
    ctx.target_id = None
    ctx.last_pos = None  # Previous position of target for velocity estimation

async def tick(bot, game, ctx):
    actions = []
    
    # 1. Target Selection
    target = game.nearest_player()
    
    if not target:
        # Patrol mode
        actions.append("move_forward")
        actions.append("jump") 
        if random.random() < 0.1:
            actions.append(f"turn_left {random.randint(30, 90)}")
        
        # Reset combat tracking
        ctx.last_pos = None
        return actions

    # 2. Combat Logic
    pos = target['position']
    dist = game.distance_to(pos)
    my_pos = game.my_position
    
    # Estimate target velocity
    target_vel = [0, 0, 0]
    if ctx.last_pos and ctx.target_id == target.get('client_num'):
        target_vel[0] = pos[0] - ctx.last_pos[0]
        target_vel[1] = pos[1] - ctx.last_pos[1]
        target_vel[2] = pos[2] - ctx.last_pos[2]
    
    ctx.last_pos = pos
    ctx.target_id = target.get('client_num')

    # 3. Weapon Selection
    best_weapon = WP_MACHINEGUN
    if dist < 400:
        # Extended close range aggression
        if random.random() < 0.1: actions.append(f"weapon {WP_ROCKET_LAUNCHER}")
        if random.random() < 0.1: actions.append(f"weapon {WP_PLASMA}") 
        if random.random() < 0.1: actions.append(f"weapon {WP_SHOTGUN}")
    elif dist < 800:
        if random.random() < 0.1: actions.append(f"weapon {WP_ROCKET_LAUNCHER}")
        if random.random() < 0.1: actions.append(f"weapon {WP_LIGHTNING}")
    else:
        if random.random() < 0.1: actions.append(f"weapon {WP_RAILGUN}")

    # 4. Aiming Logic (Splash Damage & Leading)
    aim_point = list(pos)
    
    # Lead target
    aim_point[0] += target_vel[0] * 6
    aim_point[1] += target_vel[1] * 6
    
    # Vertical aim adjustments
    if my_pos[2] > pos[2] + 20: # High ground
        aim_point[2] -= 15 # Aim at feet
    else:
        aim_point[2] += 5 # Aim at chest

    actions.append(f"aim_at {aim_point[0]} {aim_point[1]} {aim_point[2]}")
    actions.append("attack")

    # 5. Movement Logic (Orbital Strafe + Verticality)
    if dist > ctx.ideal_distance + 100:
        actions.append("move_forward")
    elif dist < ctx.ideal_distance - 50: # Allow getting slightly closer
        actions.append("move_back")
    
    # Orbit
    actions.append("move_left" if ctx.strafe_dir > 0 else "move_right")
    
    # Switch orbit direction faster
    ctx.switch_counter += 1
    if ctx.switch_counter >= ctx.switch_every:
        ctx.switch_counter = 0
        ctx.strafe_dir *= -1
        ctx.switch_every = random.randint(8, 20) # Faster switching
        
    # ANTI-GRAVITY JUMPING (Hyper-mobile)
    if random.random() < 0.9: 
        actions.append("jump")

    # 6. Personality
    if random.random() < 0.005:
        taunts = [
            "Prepare for re-entry!", 
            "Death from above!", 
            "Orbital strike inbound.", 
            "Gravity is just a suggestion.",
            "I have the high ground.",
            "Calculating impact trajectory...",
            "V2.1 online: Systems aggressive."
        ]
        actions.append(f"taunt {random.choice(taunts)}")

    return actions
