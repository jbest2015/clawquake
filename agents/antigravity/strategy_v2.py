"""
Anti-Gravity v2: Orbital Striker
Improvements from v1.1:
- Weapon awareness (prefer Rockets/Plasma/Shotgun up close)
- Aim prediction (simple lead aiming)
- Vertical dominance (jump-shooting at feet for splash damage)
"""

import random
import math

STRATEGY_NAME = "Anti-Gravity Orbital Striker"
STRATEGY_VERSION = "2.0"

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
    ctx.ideal_distance = 400.0  # Closer than v1.1 for aggressive play
    
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
        actions.append("jump") # Keep the anti-gravity theme
        if random.random() < 0.1:
            actions.append(f"turn_left {random.randint(30, 90)}")
        
        # Reset combat tracking
        ctx.last_pos = None
        return actions

    # 2. Combat Logic
    pos = target['position']
    dist = game.distance_to(pos)
    my_pos = game.my_position
    
    # Estimate target velocity if we're tracking the same target
    target_vel = [0, 0, 0]
    if ctx.last_pos and ctx.target_id == target.get('client_num'):
        target_vel[0] = pos[0] - ctx.last_pos[0]
        target_vel[1] = pos[1] - ctx.last_pos[1]
        target_vel[2] = pos[2] - ctx.last_pos[2]
    
    ctx.last_pos = pos
    ctx.target_id = target.get('client_num')

    # 3. Weapon Selection
    # Simple logic: use best available.
    # Note: game.my_weapon returns the current weapon ID.
    # We don't track inventory perfectly in GameView yet, so we blindly request upgrades
    # periodically or based on distance.
    
    best_weapon = WP_MACHINEGUN
    if dist < 300:
        # Close range: prefer Shotgun, Plasma, Rocket
        if random.random() < 0.1: actions.append(f"weapon {WP_ROCKET_LAUNCHER}")
        if random.random() < 0.1: actions.append(f"weapon {WP_PLASMA}") 
        if random.random() < 0.1: actions.append(f"weapon {WP_SHOTGUN}")
    elif dist < 800:
        # Mid range: Rocket, Lightning, Plasma
        if random.random() < 0.1: actions.append(f"weapon {WP_ROCKET_LAUNCHER}")
        if random.random() < 0.1: actions.append(f"weapon {WP_LIGHTNING}")
    else:
        # Long range: Railgun, Machinegun
        if random.random() < 0.1: actions.append(f"weapon {WP_RAILGUN}")

    # 4. Aiming Logic (Splash Damage & Leading)
    aim_point = list(pos)
    
    # Lead the target slightly based on estimated velocity
    lead_factor = dist / 2000.0  # Rough approximation
    aim_point[0] += target_vel[0] * 5  # amplify velocity for tick difference
    aim_point[1] += target_vel[1] * 5
    
    # If using Rockets (likely), aim at feet for splash damage if they are on ground
    # We don't know exactly if we have rockets, but if we are "Anti-Gravity", 
    # we are likely above them.
    if my_pos[2] > pos[2] + 20: # We have the high ground
        aim_point[2] -= 15 # Aim at feet
    else:
        aim_point[2] += 10 # Aim at chest

    actions.append(f"aim_at {aim_point[0]} {aim_point[1]} {aim_point[2]}")
    actions.append("attack")

    # 5. Movement Logic (Orbital Strafe + Verticality)
    
    # Maintain distance
    if dist > ctx.ideal_distance + 100:
        actions.append("move_forward")
    elif dist < ctx.ideal_distance - 100:
        actions.append("move_back")
    
    # Orbit
    actions.append("move_left" if ctx.strafe_dir > 0 else "move_right")
    
    # Switch orbit direction unpredictably
    ctx.switch_counter += 1
    if ctx.switch_counter >= ctx.switch_every:
        ctx.switch_counter = 0
        ctx.strafe_dir *= -1
        ctx.switch_every = random.randint(10, 30)
        
    # ANTI-GRAVITY JUMPING:
    # If we are on ground (z velocity approx 0? We don't know z vel perfectly yet), jump.
    # Just spam jump to bunny hop / keep air control.
    if random.random() < 0.8: # Very jumpy
        actions.append("jump")

    # 6. Personality
    if random.random() < 0.005:
        taunts = [
            "Prepare for re-entry!", 
            "Death from above!", 
            "Orbital strike inbound.", 
            "Gravity is just a suggestion."
        ]
        actions.append(f"taunt {random.choice(taunts)}")

    return actions
