
import unittest
from unittest.mock import Mock
from bot.game_intelligence import ItemClassifier, SpatialAwareness, CombatAnalyzer
from bot.defs import configstr_t, weapon_t

class TestGameIntelligence(unittest.TestCase):

    def setUp(self):
        self.bot = Mock()
        self.bot.game = Mock()
        self.bot.game.my_position = (0, 0, 0)
        self.bot.game.my_velocity = (0, 0, 0)
        self.bot.game.my_health = 100

    def test_classify_item(self):
        ent = Mock()
        ent.eType = 2 # ET_ITEM
        ent.modelindex = 1
        
        config_strings = {
            configstr_t.CS_MODELS + 1: "models/powerups/armor/armor_red.md3"
        }
        
        itype, subtype, val = ItemClassifier.classify(ent, config_strings)
        self.assertEqual(itype, 'armor')
        self.assertEqual(subtype, 'red')
        self.assertEqual(val, 100)

    def test_spatial_stuck(self):
        spatial = SpatialAwareness(self.bot)
        
        # Simulate not moving
        for _ in range(25):
            spatial.update()
            
        self.assertTrue(spatial.is_stuck)
        
        # Simulate moving
        self.bot.game.my_position = (100, 0, 0)
        spatial.update()
        self.assertFalse(spatial.is_stuck)

    def test_spatial_falling(self):
        spatial = SpatialAwareness(self.bot)
        
        self.bot.game.my_velocity = (0, 0, -500)
        for _ in range(10):
            spatial.update()
            
        self.assertTrue(spatial.is_falling)

    def test_combat_best_weapon(self):
        combat = CombatAnalyzer(self.bot)
        w = combat.best_weapon(200)
        self.assertEqual(w, weapon_t.WP_ROCKET_LAUNCHER)

if __name__ == '__main__':
    unittest.main()
