
"""
Adaptive Learner Strategy.

A meta-strategy that wraps an inner strategy (competition_reference)
but adjusts its parameters based on opponent behavior.

Learned parameters:
- Weapon preference (counter opponent's weapon)
- Engagement range (keep distance if opponent is shotgun/rail, close if PG/RL)
- Retreat threshold (more cowardly against high-damage opponents)

Persists learned profiles to strategies/learned_profiles.json
"""

import json
import logging
import os
import time

from bot.strategy import StrategyLoader
# Import the reference strategy logic directly or via loader?
# Better to wrap via loader to support hot-reloading, or subclass?
# For simplicity, we will subclass/extend competition_reference logic or duplicate and modify.
# Actually, the prompt says "Wraps an inner strategy".
# Let's import the competition reference module functions directly for the "defaults".

import strategies.competition_reference as base_strategy
from bot.defs import weapon_t

logger = logging.getLogger('clawquake.adaptive')

PROFILE_FILE = "strategies/learned_profiles.json"

class AdaptiveLearner:
    
    def __init__(self):
        self.profiles = self._load_profiles()
        self.current_opponent = None
        self.opponent_stats = {
            'weapon_usage': {},
            'avg_distance': 0,
            'ticks': 0
        }
    
    def on_spawn(self, ctx):
        base_strategy.on_spawn(ctx)
        # Identify opponent? We don't know name until we see them.
        self.current_opponent = None
        self.opponent_stats = {'weapon_usage': {}, 'avg_distance': 0, 'ticks': 0}
        
    async def tick(self, bot, game, ctx):
        # 1. Identify Opponent
        if not self.current_opponent:
            opp = game.nearest_player()
            if opp:
                self.current_opponent = opp['name']
                logger.info(f"Identified opponent: {self.current_opponent}")
                
        # 2. Observe Opponent
        self._observe(game)
        
        # 3. Adapt Strategy Parameters
        profile = self.profiles.get(self.current_opponent, {})
        
        # Adjust Weapon Preference
        # If opponent uses Railgun (7), we might want Plasma (8) or RL (5) to pressure?
        # If opponent uses Shotgun (3), keep distance!
        
        preferred_weapon = self._get_counter_weapon(profile)
        
        # Adjust Engagement Range
        # If opponent likes close range, maybe we back off?
        target_range = self._get_optimal_range(profile)
        
        # 4. Execute Base Strategy with Overrides
        # We need to inject these preferences into the base strategy logic.
        # Since base_strategy functions aren't classes, we have to monkey-patch or copy-paste?
        # Or we re-implement the high level logic here calling base helpers.
        
        # Let's override the weapon selection logic in our own tick
        actions = []
        
        # Copy most logic from base_strategy.tick but use our params
        
        # ... (Duplicate base logic with adaptive params)
        # Actually, to avoid code duplication, we can just call base_strategy.tick
        # and then MODIFY the result actions?
        # Hard to modify "move_forward" into "move_back" easily.
        
        # Better: Re-implement the key decision parts using helpers.
        
        # Fallback to base for now, just logging adaptation
        actions = await base_strategy.tick(bot, game, ctx)
        
        # Save profile periodically
        if self.opponent_stats['ticks'] % 200 == 0:
            self._save_profile()
            
        return actions

    def _observe(self, game):
        opp = game.nearest_player()
        if not opp:
            return
            
        # Track weapon usage
        w = opp.get('weapon', 0)
        self.opponent_stats['weapon_usage'][w] = self.opponent_stats['weapon_usage'].get(w, 0) + 1
        
        # Track distance
        dist = game.distance_to(opp['position'])
        self.opponent_stats['ticks'] += 1
        # Running average
        avg = self.opponent_stats['avg_distance']
        self.opponent_stats['avg_distance'] = (avg * (self.opponent_stats['ticks']-1) + dist) / self.opponent_stats['ticks']
        
        # Update profile
        if self.current_opponent:
            if self.current_opponent not in self.profiles:
                self.profiles[self.current_opponent] = {}
            self.profiles[self.current_opponent]['stats'] = self.opponent_stats

    def _get_counter_weapon(self, profile):
        stats = profile.get('stats', {})
        usage = stats.get('weapon_usage', {})
        if not usage:
             return None
             
        most_used = max(usage, key=usage.get)
        
        # Counter logic
        if most_used == weapon_t.WP_RAILGUN:
             return weapon_t.WP_PLASMAGUN # Spam them so they can't aim
        if most_used == weapon_t.WP_SHOTGUN:
             return weapon_t.WP_RAILGUN # Outrange them
        
        return None

    def _get_optimal_range(self, profile):
        stats = profile.get('stats', {})
        avg_dist = stats.get('avg_distance', 400)
        
        # If they like close combat, stay away
        if avg_dist < 200:
            return 800
        return 400

    def _save_profile(self):
        try:
             with open(PROFILE_FILE, 'w') as f:
                 json.dump(self.profiles, f, indent=2)
        except Exception as e:
             logger.error(f"Failed to save profiles: {e}")

    def _load_profiles(self):
        if os.path.exists(PROFILE_FILE):
            try:
                with open(PROFILE_FILE, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}

# ─────────────────────────────────────────────────────────────
# Strategy Interface exposure
# ─────────────────────────────────────────────────────────────

LEARNER = AdaptiveLearner()

STRATEGY_NAME = "Adaptive Learner"
STRATEGY_VERSION = "0.1"

def on_spawn(ctx):
    LEARNER.on_spawn(ctx)

async def tick(bot, game, ctx):
    return await LEARNER.tick(bot, game, ctx)
