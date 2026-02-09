
import unittest
from unittest.mock import Mock, patch
from strategies.adaptive_learner import AdaptiveLearner, weapon_t
import json
import os

class TestAdaptiveLearner(unittest.TestCase):
    
    def setUp(self):
        self.learner = AdaptiveLearner()
        self.learner.profiles = {}
        
    def test_observe_opponent(self):
        game = Mock()
        game.nearest_player.return_value = {
            'name': 'BotB',
            'position': (100, 0, 0),
            'weapon': weapon_t.WP_RAILGUN
        }
        game.distance_to.return_value = 100
        
        # Identified first
        self.learner.current_opponent = 'BotB'
        
        self.learner._observe(game)
        
        stats = self.learner.profiles['BotB']['stats']
        self.assertEqual(stats['weapon_usage'][weapon_t.WP_RAILGUN], 1)
        self.assertEqual(stats['avg_distance'], 100)
        
    def test_counter_weapon(self):
        profile = {
            'stats': {
                'weapon_usage': {
                    weapon_t.WP_RAILGUN: 50,
                    weapon_t.WP_SHOTGUN: 10
                }
            }
        }
        w = self.learner._get_counter_weapon(profile)
        self.assertEqual(w, weapon_t.WP_PLASMAGUN) # Counter to Rail
        
        profile['stats']['weapon_usage'] = {
            weapon_t.WP_SHOTGUN: 100
        }
        w = self.learner._get_counter_weapon(profile)
        self.assertEqual(w, weapon_t.WP_RAILGUN) # Counter to Shotgun
        
    def test_optimal_range(self):
        profile = {
            'stats': {
                'avg_distance': 100 # Close range fighter
            }
        }
        r = self.learner._get_optimal_range(profile)
        self.assertEqual(r, 800) # Stay away!
        
    def tearDown(self):
        if os.path.exists("test_profiles.json"):
            os.remove("test_profiles.json")

if __name__ == '__main__':
    unittest.main()
