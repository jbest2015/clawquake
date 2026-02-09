
import unittest
import json
import os
import shutil
from bot.replay_recorder import ReplayRecorder
from bot.replay_recorder import ReplayLoader

class TestReplayRecorder(unittest.TestCase):
    
    def setUp(self):
        self.match_id = "test_match_123"
        self.bot_name = "BotA"
        # Use temp dir
        self.orig_dir = "replays"
        if not os.path.exists("test_replays"):
            os.makedirs("test_replays")
        # Monkey patch loader/recorder dir
        from bot import replay_recorder
        replay_recorder.REPLAY_DIR = "test_replays"
        
        self.recorder = ReplayRecorder(self.match_id, self.bot_name)
        
    def tearDown(self):
        shutil.rmtree("test_replays")
        
    def test_record_tick(self):
        game = Mock()
        game.my_position = (10, 20, 30)
        game.my_velocity = (100, 0, 0)
        game.my_health = 100
        game.my_weapon = 5
        game.players = [{'name': 'BotB', 'pos': (50, 50, 0)}]
        game.items = []
        
        self.recorder.record_tick(game)
        
        self.assertEqual(len(self.recorder.ticks), 1)
        tick = self.recorder.ticks[0]
        self.assertEqual(tick['my_pos'], [10, 20, 30])
        self.assertEqual(tick['my_health'], 100)
        
    def test_record_event(self):
        self.recorder.record_event('kill', {'victim': 'BotB'})
        self.assertEqual(len(self.recorder.events), 1)
        evt = self.recorder.events[0]
        self.assertEqual(evt['type'], 'kill')
        self.assertEqual(evt['data']['victim'], 'BotB')
        
    def test_save_and_load(self):
        self.recorder.record_event('test', {})
        self.recorder.save()
        
        loader = ReplayLoader(self.recorder.filepath)
        ok = loader.load()
        self.assertTrue(ok)
        
        self.assertEqual(len(loader.get_events()), 1)
        self.assertEqual(loader.summary()['ticks'], 0)
        
from unittest.mock import Mock

if __name__ == '__main__':
    unittest.main()
