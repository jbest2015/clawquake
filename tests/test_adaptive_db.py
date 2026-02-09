
import unittest
from unittest.mock import Mock, patch, MagicMock
import json
import os
import shutil
from datetime import datetime

# We need to test the logic WITHOUT import errors
# Since we might not have 'orchestrator' available in running context if ran standalone?
# But we are in correct CWD.
from strategies.adaptive_learner import AdaptiveLearner, OpponentProfileDB

class TestAdaptiveDB(unittest.TestCase):
    
    def setUp(self):
        self.learner = AdaptiveLearner()
        self.learner.profiles = {}
        
    @patch('strategies.adaptive_learner.SessionLocal')
    @patch('strategies.adaptive_learner.DB_AVAILABLE', True)
    def test_save_to_db(self, mock_session_cls):
        # Mock session
        session = MagicMock()
        mock_session_cls.return_value = session
        
        # Setup existing profile query
        opp_mock = MagicMock()
        opp_mock.weapon_counts = "{}"
        session.query().filter_by().first.return_value = opp_mock
        
        self.learner.current_opponent = "BotX"
        self.learner.opponent_stats = {
            'weapon_usage': {7: 10},
            'avg_distance': 500,
            'ticks': 100
        }
        self.learner.profiles["BotX"] = {}
        
        self.learner._save_profile()
        
        # Check commit
        session.commit.assert_called()
        # Check update
        self.assertIn('7": 10', opp_mock.weapon_counts)
        self.assertEqual(opp_mock.engagement_range_avg, 500)
        
    @patch('strategies.adaptive_learner.SessionLocal')
    @patch('strategies.adaptive_learner.DB_AVAILABLE', True)
    def test_load_from_db(self, mock_session_cls):
        session = MagicMock()
        mock_session_cls.return_value = session
        
        opp_mock = MagicMock()
        opp_mock.weapon_counts = '{"7": 5}'
        opp_mock.engagement_range_avg = 300
        session.query().filter_by().first.return_value = opp_mock
        
        self.learner._load_from_db("BotY")
        
        self.assertIn("BotY", self.learner.profiles)
        stats = self.learner.profiles["BotY"]["stats"]
        self.assertEqual(stats["weapon_usage"]["7"], 5)
        self.assertEqual(stats["avg_distance"], 300)

if __name__ == '__main__':
    unittest.main()
