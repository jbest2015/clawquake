
"""
Game Intelligence Utilities.

Provides high-level analysis of the game state for AI decision making.
Includes:
- Item classification (health vs armor vs weapon vs ammo)
- Spatial awareness (am I falling? am I stuck?)
- Combat analysis (best weapon, distance logic, lead prediction)
"""

import math
from .defs import weapon_t, entityType_t, meansOfDeath_t, configstr_t

class ItemClassifier:
    """Helper to classify entities as specific item types."""
    
    @staticmethod
    def classify(entity, config_strings):
        """
        Classify a game entity into a useful type/subtype.
        Returns (type, subtype, value) tuple.
        e.g. ('health', 'large', 50) or ('weapon', 'rocket', 5)
        """
        if entity.entity_type == entityType_t.ET_ITEM:
            # Check model index against known item models in configstrings
            model_idx = entity.fields.get('modelindex', 0)
            if not config_strings:
                return ('item', 'unknown', 0)
                
            model_name = config_strings.get(configstr_t.CS_MODELS + model_idx, "")
            model_lower = model_name.lower()
            
            if 'health' in model_lower:
                val = 50 if 'large' in model_lower or 'mega' in model_lower else 25
                subtype = 'mega' if 'mega' in model_lower else 'large' if 'large' in model_lower else 'medium'
                return ('health', subtype, val)
            elif 'armor' in model_lower:
                val = 100 if 'heavy' in model_lower or 'red' in model_lower else 50
                subtype = 'red' if 'red' in model_lower else 'yellow'
                return ('armor', subtype, val)
            elif 'weapon' in model_lower or 'ammo' in model_lower:
                # Extract weapon name
                for w in ['rocket', 'railgun', 'plasma', 'shotgun', 'grenade', 'lightning', 'bfg', 'machinegun']:
                    if w in model_lower:
                        return ('weapon' if 'weapon' in model_lower else 'ammo', w, 0)
            
            return ('item', model_name, 0)
            
        return ('unknown', 'unknown', 0)


class SpatialAwareness:
    """Analyzes bot's spatial state."""

    def __init__(self, bot):
        self.bot = bot
        self.last_pos = (0, 0, 0)
        self.stuck_ticks = 0
        self.fall_ticks = 0

    def update(self):
        """Called every tick to update internal state trackers."""
        current_pos = self.bot.game.my_position
        
        # Stuck detection
        if self._dist(current_pos, self.last_pos) < 1.0:
            self.stuck_ticks += 1
        else:
            self.stuck_ticks = 0
        self.last_pos = current_pos

        # Fall detection (negative Z velocity)
        vel_z = self.bot.game.my_velocity[2]
        if vel_z < -300: # Falling fast
            self.fall_ticks += 1
        else:
            self.fall_ticks = 0

    @property
    def is_stuck(self):
        return self.stuck_ticks > 20 # ~1 second

    @property
    def is_falling(self):
        return self.fall_ticks > 5 # ~0.25 seconds of fast falling

    def _dist(self, a, b):
        return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)


class CombatAnalyzer:
    """Analyzes combat situations and provides aim assistance."""

    def __init__(self, bot):
        self.bot = bot
        self.enemy_history = {} # client_num -> [(time, pos), ...]
        
    def update(self):
        """Track enemy movement for velocity calculation."""
        current_time = self.bot.game.server_time
        
        # Use set for rapid cleanup checks
        visible_clients = set()
        
        # We need to access players from game view.
        # Ideally GameView.players gives us client_num and position.
        players = self.bot.game.players
        
        for p in players:
            cnum = p['client_num']
            pos = p['position']
            visible_clients.add(cnum)
            
            if cnum not in self.enemy_history:
                self.enemy_history[cnum] = []
            
            self.enemy_history[cnum].append((current_time, pos))
            
            # Prune old history (>500ms)
            self.enemy_history[cnum] = [
                (t, pos) for t, pos in self.enemy_history[cnum]
                if current_time - t < 500
            ]
            
        # Clean up stale enemies who haven't been seen in >5 seconds?
        # For now, just keep the dict clean of unconnected clients
        # We let history persist briefly for prediction if they duck behind cover
        pass

    def get_enemy_velocity(self, client_num):
        """Estimate enemy velocity from history."""
        hist = self.enemy_history.get(client_num)
        if not hist or len(hist) < 2:
            return (0, 0, 0)
            
        t_now, pos_now = hist[-1]
        
        # Look for a sample ~100-200ms ago for stable delta
        target_t = t_now - 150
        best_prev = hist[0]
        
        for t, p in reversed(hist[:-1]):
            if t <= target_t:
                best_prev = (t, p)
                break
        
        t_prev, pos_prev = best_prev
        dt = (t_now - t_prev) / 1000.0
        
        if dt <= 0.001: return (0, 0, 0)
        
        vx = (pos_now[0] - pos_prev[0]) / dt
        vy = (pos_now[1] - pos_prev[1]) / dt
        vz = (pos_now[2] - pos_prev[2]) / dt
        
        return (vx, vy, vz)

    def get_lead_position(self, target, weapon_id):
        """
        Calculate where to aim to hit the target.
        Returns (x, y, z) predicted prediction.
        """
        if not target:
            return None
            
        # Weapon projectile speeds
        speeds = {
            weapon_t.WP_ROCKET_LAUNCHER: 900,
            weapon_t.WP_PLASMAGUN: 2000,
            weapon_t.WP_GRENADE_LAUNCHER: 700,
            weapon_t.WP_BFG: 2000,
        }
        
        speed = speeds.get(int(weapon_id))
        
        # If instantaneous (Rail/Machinegun/Lightning/Shotgun), return direct pos
        # (Technically should account for ping/interpolation, but local is 0 ping)
        if not speed:
            return target['position']
            
        target_pos = list(target['position'])
        my_pos = self.bot.game.my_position
        
        dist = self.bot.game.distance_to(target_pos)
        t_flight = dist / speed
        
        # Get target velocity
        vx, vy, vz = self.get_enemy_velocity(target['client_num'])
        
        pred_x = target_pos[0] + vx * t_flight
        pred_y = target_pos[1] + vy * t_flight
        pred_z = target_pos[2] + vz * t_flight
        
        return (pred_x, pred_y, pred_z)
    
    def best_weapon(self, target_dist):
        """Recommend best available weapon for distance."""
        # This is a placeholder; real logic would check inventory
        return weapon_t.WP_ROCKET_LAUNCHER

    def should_retreat(self):
        return self.bot.game.my_health < 30
