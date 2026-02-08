
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
        self.game.items = []
        self.game.my_position = (0, 0, 0)
        self.game.my_velocity = (0, 0, 0)
        self.game.my_health = 100
        self.game.my_weapon = 1
        self.game.nearest_player.return_value = None
        self.game.distance_to.return_value = 0
        self.game.am_i_falling = False
        self.game.am_i_stuck = False
        self.game.suggest_weapon.return_value = 1
        self.game.server_time = 0
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

        # Setup game mock behavior — not falling, not stuck, no enemies
        self.game.my_position = (0, 0, 0)
        self.game.my_velocity = (0, 0, 0)
        self.game.my_health = 100
        self.game.my_weapon = 1
        self.game.players = []
        self.game.entities = {}
        self.game.items = []
        self.game.nearest_player.return_value = None
        self.game.distance_to.return_value = 0
        self.game.am_i_falling = False
        self.game.am_i_stuck = False

        # Run tick — with no enemies or items, should roam
        actions = asyncio.run(self.loader.tick(self.bot, self.game))

        # Expect some actions (move, jump, etc.)
        self.assertTrue(len(actions) > 0)
        self.assertIn("move_forward", actions)

    def test_context_persistence(self):
        self._reset_and_spawn()

        # Setup mocks — not falling, not stuck initially
        self.game.my_position = (0, 0, 0)
        self.game.my_velocity = (0, 0, 0)
        self.game.am_i_falling = False
        self.game.am_i_stuck = False
        self.game.items = []

        # First tick — roaming, should set context state
        asyncio.run(self.loader.tick(self.bot, self.game))

        # Verify context persists across ticks (retreating starts False)
        self.assertFalse(self.ctx.retreating)

        # Set low health — retreat should activate
        self.game.my_health = 20
        asyncio.run(self.loader.tick(self.bot, self.game))
        self.assertTrue(self.ctx.retreating)

        # Context persists: retreating remains True even after another tick
        # at same health
        asyncio.run(self.loader.tick(self.bot, self.game))
        self.assertTrue(self.ctx.retreating)

    def test_retreat_logic(self):
        self._reset_and_spawn()

        # Setup mocks — not falling, not stuck
        self.game.my_position = (0, 0, 0)
        self.game.my_velocity = (0, 0, 0)
        self.game.players = []
        self.game.entities = {}
        self.game.items = []
        self.game.nearest_player.return_value = None
        self.game.distance_to.return_value = 0
        self.game.am_i_falling = False
        self.game.am_i_stuck = False

        self.game.my_health = 20  # Low health
        asyncio.run(self.loader.tick(self.bot, self.game))
        self.assertTrue(self.ctx.retreating)

        self.game.my_health = 100
        asyncio.run(self.loader.tick(self.bot, self.game))
        self.assertFalse(self.ctx.retreating)

if __name__ == '__main__':
    unittest.main()
