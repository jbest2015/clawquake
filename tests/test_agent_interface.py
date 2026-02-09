
import unittest
from unittest.mock import Mock, patch
from orchestrator.ai_agent_interface import LATEST_STATES, ACTION_QUEUES

class TestAgentInterface(unittest.TestCase):
    
    def setUp(self):
        LATEST_STATES.clear()
        ACTION_QUEUES.clear()
        
    def test_observe_no_data(self):
        # Simulate fetch with ID 1
        state = LATEST_STATES.get(1)
        self.assertIsNone(state)
        
    def test_observe_with_data(self):
        LATEST_STATES[1] = {'tick': 100, 'health': 100}
        state = LATEST_STATES.get(1)
        self.assertEqual(state['tick'], 100)
        
    def test_act_queueing(self):
        bot_id = 99
        action = {'action': 'move_forward', 'params': {}}
        
        if bot_id not in ACTION_QUEUES:
            ACTION_QUEUES[bot_id] = []
        ACTION_QUEUES[bot_id].append(action)
        
        self.assertEqual(len(ACTION_QUEUES[99]), 1)
        self.assertEqual(ACTION_QUEUES[99][0]['action'], 'move_forward')
        
    def test_sync_runner(self):
        # Simulate runner syncing
        bot_id = 5
        LATEST_STATES[bot_id] = {'tick': 50}
        
        # Add pending action
        ACTION_QUEUES[bot_id] = [{'action': 'jump'}]
        
        # Runner reads actions
        actions = ACTION_QUEUES[bot_id]
        ACTION_QUEUES[bot_id] = [] # Clear
        
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['action'], 'jump')
        self.assertEqual(len(ACTION_QUEUES[bot_id]), 0)

if __name__ == '__main__':
    unittest.main()
