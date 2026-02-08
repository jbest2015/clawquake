
import unittest
from unittest.mock import Mock, patch
from bot.event_stream import EventStream
import json
import time

class TestEventStream(unittest.TestCase):

    def setUp(self):
        self.stream = EventStream("http://orchestrator:8000", "secret", "match-123")

    @patch('urllib.request.urlopen')
    def test_emit_kill(self, mock_urlopen):
        mock_response = Mock()
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=None)
        mock_urlopen.return_value = mock_response

        # Force synchronous send for test
        self.stream._send_sync('kill', {'killer': 'BotA', 'victim': 'BotB', 'weapon': 'railgun'})

        args, kwargs = mock_urlopen.call_args
        req = args[0]
        
        self.assertEqual(req.full_url, "http://orchestrator:8000/api/internal/match/match-123/events")
        data = json.loads(req.data.decode('utf-8'))
        self.assertEqual(data['type'], 'kill')
        self.assertEqual(data['match_id'], 'match-123')
        self.assertEqual(data['data']['killer'], 'BotA')

    @patch('urllib.request.urlopen')
    def test_emit_disabled(self, mock_urlopen):
        # Disabled stream (no orchestrator URL)
        disabled_stream = EventStream(None, None, None)
        disabled_stream._send_sync('test', {})
        mock_urlopen.assert_not_called()

if __name__ == '__main__':
    unittest.main()
