
"""
Event Stream for Real-Time Orchestrator Updates.

Sends JSON events to /api/internal/event_stream (or similar endpoint)
during the match, allowing spectators to see kills/items/scores live.
"""

import time
import json
import logging
import asyncio
import urllib.request
import urllib.error

logger = logging.getLogger('clawquake.eventstream')

class EventStream:
    """Emits game events to the external world."""

    def __init__(self, orchestrator_url, internal_secret, match_id):
        self.url = f"{orchestrator_url}/api/internal/match/{match_id}/events"
        self.secret = internal_secret
        self.match_id = match_id
        self._enabled = bool(orchestrator_url and match_id)
        
    def _send(self, event_type, data):
        """Synchronous event send — delegates to _send_sync."""
        self._send_sync(event_type, data)

    async def emit_async(self, event_type, data):
        """Async emit to avoid blocking the game loop."""
        if not self._enabled:
            return
            
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._send_sync, event_type, data)
        
    def _send_sync(self, event_type, data):
         if not self._enabled: return
         
         payload = {
            'type': event_type, 
            'match_id': self.match_id,
            'timestamp': time.time(),
            'data': data
         }
         
         try:
            req = urllib.request.Request(
                self.url,
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'X-Internal-Secret': self.secret
                },
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=1.0) as f:
                pass
         except Exception as e:
            # Squelch errors to keep game running
            pass

    def emit_kill(self, killer, victim, weapon):
        asyncio.create_task(self.emit_async('kill', {
            'killer': killer,
            'victim': victim,
            'weapon': weapon
        }))

    def emit_score(self, bot_name, score):
        asyncio.create_task(self.emit_async('score', {
            'bot': bot_name,
            'score': score
        }))

    def emit_chat(self, sender, message):
        asyncio.create_task(self.emit_async('chat', {
            'sender': sender,
            'message': message
        }))
