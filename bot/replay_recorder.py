
"""
Replay Recorder and Loader.

Records game state ticks to JSON for replay analysis.
"""

import json
import time
import os
import logging
from datetime import datetime

logger = logging.getLogger('clawquake.replay')

REPLAY_DIR = "replays"

class ReplayRecorder:
    
    def __init__(self, match_id, bot_name):
        self.match_id = match_id
        self.bot_name = bot_name
        self.ticks = []
        self.events = []
        self.start_time = time.time()
        self.metadata = {
            'match_id': match_id,
            'bot_name': bot_name,
            'timestamp': datetime.utcnow().isoformat(),
            'duration': 0
        }
        
        if not os.path.exists(REPLAY_DIR):
            os.makedirs(REPLAY_DIR)
            
        self.filepath = os.path.join(REPLAY_DIR, f"{match_id}_{bot_name}.json")
        logger.info(f"Recording replay to {self.filepath}")

    def record_tick(self, game_view):
        """Record game state for this tick."""
        tick_data = {
            'time': time.time() - self.start_time,
            'my_pos': list(game_view.my_position),
            'my_vel': list(game_view.my_velocity),
            'my_health': game_view.my_health,
            'my_weapon': game_view.my_weapon,
            'players': game_view.players, # Includes positions of others
            'items': game_view.items if hasattr(game_view, 'items') else [],
        }
        self.ticks.append(tick_data)

    def record_event(self, event_type, data):
        """Record discrete event (kill, death, chat)."""
        event_data = {
            'time': time.time() - self.start_time,
            'type': event_type,
            'data': data
        }
        self.events.append(event_data)

    def save(self):
        """Save replay to disk."""
        self.metadata['duration'] = time.time() - self.start_time
        self.metadata['tick_count'] = len(self.ticks)
        
        data = {
            'metadata': self.metadata,
            'ticks': self.ticks,
            'events': self.events
        }
        
        try:
            with open(self.filepath, 'w') as f:
                json.dump(data, f, indent=None) # Compact JSON
            logger.info(f"Replay saved: {self.filepath} ({len(self.ticks)} ticks)")
        except Exception as e:
            logger.error(f"Failed to save replay: {e}")

class ReplayLoader:
    
    def __init__(self, filepath):
        self.filepath = filepath
        self.data = None
        
    def load(self):
        try:
            with open(self.filepath, 'r') as f:
                self.data = json.load(f)
            return True
        except Exception as e:
            logger.error(f"Failed to load replay: {e}")
            return False

    def get_tick(self, index):
        if not self.data or index < 0 or index >= len(self.data['ticks']):
            return None
        return self.data['ticks'][index]

    def get_events(self, event_type=None):
        if not self.data:
            return []
        if event_type:
            return [e for e in self.data['events'] if e['type'] == event_type]
        return self.data['events']

    def summary(self):
        if not self.data:
            return {}
        meta = self.data['metadata']
        return {
            'duration': meta.get('duration', 0),
            'ticks': meta.get('tick_count', 0),
            'kills': len(self.get_events('kill')),
            'deaths': len(self.get_events('death')),
        }
