
"""
Game Intelligence Utilities.

Provides high-level analysis of the game state for AI decision making.
Includes:
- Item classification (health vs armor vs weapon vs ammo)
- Spatial awareness (am I falling? am I stuck?)
- Combat analysis (best weapon, distance logic)
"""

import math
from .defs import weapon_t, entityType_t, meansOfDeath_t, configstr_t

class ItemClassifier:
    """Helper to classify entities as specific item types."""
    
    # Map common model names/sounds to checking logic if needed
    # But Q3 communicates items via configstrings usually.
    # Here we classify based on basic heuristics or configstring lookup if available.

    @staticmethod
    def classify(entity, config_strings):
        """
        Classify a game entity into a useful type/subtype.
        Returns (type, subtype, value) tuple.
        e.g. ('health', 'large', 50) or ('weapon', 'rocket', 5)
        """
        if entity.eType == entityType_t.ET_ITEM:
            # Check model index against known item models in configstrings
            model_idx = entity.modelindex
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
    """Analyzes combat situations."""

    def __init__(self, bot):
        self.bot = bot
    
    def best_weapon(self, target_dist):
        """Recommend best available weapon for distance."""
        # Simple logical ordering based on possession and ammo (if we tracked ammo properly)
        # Ideally we check self.bot.game.my_ammo if populated.
        
        # Priority map: (weapon, min_dist, max_dist)
        # We assume we have the weapon if we used it recently or check inventory logic
        # For now, we return a preference list.
        return weapon_t.WP_ROCKET_LAUNCHER # Placeholder logic

    def should_retreat(self):
        """Simple health check."""
        return self.bot.game.my_health < 30
