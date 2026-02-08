
import unittest
import asyncio
from unittest.mock import Mock, MagicMock
from bot.bot import ClawBot, GameView
from bot.strategy import StrategyLoader
import sys
import os

# Ensure strategy loader can find the files
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestStrategy(unittest.TestCase):

    def setUp(self):
        self.bot = Mock(spec=ClawBot)
        self.bot.client = Mock()
        self.bot.client.config_strings = {}
        self.game = Mock(spec=GameView)
        # Default mock values to avoid TypeErrors
        self.game.players = []
        self.game.entities = {}
        self.game.my_position = (0, 0, 0)
        self.game.my_velocity = (0, 0, 0)
        self.game.my_health = 100
        self.game.my_weapon = 1
        self.game.nearest_player.return_value = None
        self.game.distance_to.return_value = 0
        self.loader = StrategyLoader("strategies/competition_reference.py")

    @property
    def ctx(self):
        return self.loader.context

    def _reset_and_spawn(self):
        # Reset context
        if hasattr(self.ctx, 'reset'):
            self.ctx.reset()
        # Call on_spawn
        if 'on_spawn' in self.loader._namespace:
            self.loader._namespace['on_spawn'](self.ctx)

    def test_strategy_loader_loads_file(self):
        self.assertEqual(self.loader.name, "Competition Reference")
        self.assertEqual(self.loader.version, "1.0")
        
    def test_strategy_tick_returns_actions(self):
        self._reset_and_spawn()
        
        # Setup game mock behavior
        # Need to ensure properties return values, not Mocks
        self.game.my_position = (0, 0, 0)
        self.game.my_velocity = (0, 0, 0) # This tuple is subscriptable
        self.game.my_health = 100
        self.game.my_weapon = 1
        self.game.players = []
        self.game.entities = {}
        self.game.nearest_player.return_value = None
        self.game.distance_to.return_value = 0
        
        # Run tick
        actions = asyncio.run(self.loader.tick(self.bot, self.game))
        
        # Expect some actions (move, jump, etc.)
        self.assertTrue(len(actions) > 0)
        self.assertIn("move_forward", actions)

    def test_context_persistence(self):
        self._reset_and_spawn()
        initial_tick = getattr(self.ctx, 'stuck_ticks', 0)
        
        # Setup mocks
        self.game.my_position = (0, 0, 0)
        self.game.my_velocity = (0, 0, 0)
        
        # Run a tick where we simulate being stuck
        self.ctx.last_pos = (0, 0, 0) # Force stuck
        asyncio.run(self.loader.tick(self.bot, self.game))
        
        self.assertTrue(getattr(self.ctx, 'stuck_ticks', 0) > initial_tick)

    def test_retreat_logic(self):
        self._reset_and_spawn()
        
        # Setup mocks
        self.game.my_position = (0, 0, 0)
        self.game.my_velocity = (0, 0, 0)
        self.game.players = []
        self.game.entities = {}
        self.game.nearest_player.return_value = None
        self.game.distance_to.return_value = 0
        
        self.game.my_health = 20 # Low health
        asyncio.run(self.loader.tick(self.bot, self.game))
        self.assertTrue(self.ctx.retreating)
        
        self.game.my_health = 100
        asyncio.run(self.loader.tick(self.bot, self.game))
        self.assertFalse(self.ctx.retreating)

if __name__ == '__main__':
    unittest.main()
