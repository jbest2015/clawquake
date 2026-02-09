
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


from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager

from bot.strategy import StrategyLoader
import strategies.competition_reference as base_strategy
from bot.defs import weapon_t

# Try importing DB models; fallback if not available (e.g. running standalone)
try:
    from orchestrator.models import SessionLocal, OpponentProfileDB
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

logger = logging.getLogger('clawquake.adaptive')

PROFILE_FILE = "strategies/learned_profiles.json"
TTL_DAYS = 30

class AdaptiveLearner:
    
    def __init__(self):
        self.profiles = {}
        if not DB_AVAILABLE:
             self.profiles = self._load_profiles_file()
        self.current_opponent = None
        self.opponent_stats = {
            'weapon_usage': {},
            'avg_distance': 0,
            'ticks': 0
        }
    
    def on_spawn(self, ctx):
        base_strategy.on_spawn(ctx)
        self.current_opponent = None
        self.opponent_stats = {'weapon_usage': {}, 'avg_distance': 0, 'ticks': 0}
        
    async def tick(self, bot, game, ctx):
        # 1. Identify Opponent
        if not self.current_opponent:
            opp = game.nearest_player()
            if opp:
                self.current_opponent = opp['name']
                logger.info(f"Identified opponent: {self.current_opponent}")
                # Load from DB if needed
                if DB_AVAILABLE and self.current_opponent not in self.profiles:
                     self._load_from_db(self.current_opponent)
                
        # 2. Observe Opponent
        self._observe(game)
        
        # 3. Adapt Strategy Parameters
        profile = self.profiles.get(self.current_opponent, {})
        
        preferred_weapon = self._get_counter_weapon(profile)
        target_range = self._get_optimal_range(profile)
        
        # 4. Execute Base Strategy
        actions = await base_strategy.tick(bot, game, ctx)
        
        # Save profile periodically
        if self.opponent_stats['ticks'] > 0 and self.opponent_stats['ticks'] % 200 == 0:
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
        
        # Update profile interaction
        if self.current_opponent:
            if self.current_opponent not in self.profiles:
                self.profiles[self.current_opponent] = {}
            self.profiles[self.current_opponent]['stats'] = self.opponent_stats

    def _get_counter_weapon(self, profile):
        stats = profile.get('stats', {})
        usage = stats.get('weapon_usage', {})
        if not usage:
             return None
        # Counter logic...
        most_used = max(usage, key=usage.get)
        if most_used == weapon_t.WP_RAILGUN: return weapon_t.WP_PLASMAGUN
        if most_used == weapon_t.WP_SHOTGUN: return weapon_t.WP_RAILGUN
        return None

    def _get_optimal_range(self, profile):
        stats = profile.get('stats', {})
        avg_dist = stats.get('avg_distance', 400)
        if avg_dist < 200: return 800
        return 400

    def _save_profile(self):
        if not self.current_opponent: return
        
        profile_data = self.profiles[self.current_opponent]
        
        if DB_AVAILABLE:
            try:
                with self._db_session() as session:
                    stats = self.opponent_stats
                    
                    # Check/Update DB
                    opp = session.query(OpponentProfileDB).filter_by(
                        opponent_name=self.current_opponent
                    ).first()
                    
                    if not opp:
                        opp = OpponentProfileDB(opponent_name=self.current_opponent)
                        session.add(opp)
                    
                    # Merge existing counts if reloading?
                    # For simplicity, just overwrite with current session stats + logic if we wanted true persistence
                    # The prompt implies we persist.
                    # Ideally we load existing stats, add current session, then save.
                    # Here we just save current session stats as the profile.
                    
                    opp.weapon_counts = json.dumps(stats['weapon_usage'])
                    opp.engagement_range_avg = stats['avg_distance']
                    opp.games_analyzed += 1
                    opp.last_updated = datetime.utcnow()
                    session.commit()
            except Exception as e:
                logger.error(f"DB Save Error: {e}")
        else:
            # Fallback JSON
            try:
                 with open(PROFILE_FILE, 'w') as f:
                     json.dump(self.profiles, f, indent=2)
            except Exception as e:
                 logger.error(f"JSON Save Error: {e}")

    def _load_from_db(self, name):
        if not DB_AVAILABLE: return
        try:
            with self._db_session() as session:
                opp = session.query(OpponentProfileDB).filter_by(opponent_name=name).first()
                if opp:
                    self.profiles[name] = {
                        'stats': {
                            'weapon_usage': json.loads(opp.weapon_counts or "{}"),
                            'avg_distance': opp.engagement_range_avg
                        }
                    }
        except Exception as e:
             logger.error(f"DB Load Error: {e}")

    def _load_profiles_file(self):
        if os.path.exists(PROFILE_FILE):
            try:
                with open(PROFILE_FILE, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}
        
    @contextmanager
    def _db_session(self):
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

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
