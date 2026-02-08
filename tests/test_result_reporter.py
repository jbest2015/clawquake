
import unittest
from unittest.mock import Mock, patch
from bot.result_reporter import ResultReporter
import json

class TestResultReporter(unittest.TestCase):

    def setUp(self):
        self.reporter = ResultReporter("http://localhost:8000", "my_secret")

    @patch('urllib.request.urlopen')
    def test_report_match_success(self, mock_urlopen):
        match_id = "test-match-123"
        bot_id = 1
        stats = {"kills": 10, "deaths": 2}
        
        # Configure mock response
        mock_response = Mock()
        mock_response.status = 200
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=None)
        mock_urlopen.return_value = mock_response

        ok = self.reporter.report_match_result(match_id, bot_id, stats)
        
        self.assertTrue(ok)
        
        # Verify request
        args, kwargs = mock_urlopen.call_args
        req = args[0]
        
        self.assertEqual(req.full_url, "http://localhost:8000/api/internal/match/report")
        # Verify headers (case-insensitive check)
        headers = {k.lower(): v for k, v in req.header_items()}
        self.assertEqual(headers.get('x-internal-secret'), 'my_secret')
        self.assertEqual(req.get_method(), 'POST')
        
        # Check payload
        payload = json.loads(req.data.decode('utf-8'))
        self.assertEqual(payload['match_id'], match_id)
        self.assertEqual(payload['bot_id'], bot_id)
        self.assertEqual(payload['stats'], stats)

    @patch('urllib.request.urlopen')
    def test_report_match_connection_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        
        ok = self.reporter.report_match_result("mid", 1, {})
        self.assertFalse(ok)

    @patch('urllib.request.urlopen')
    def test_report_match_http_error(self, mock_urlopen):
        import urllib.error
        err = urllib.error.HTTPError("url", 403, "Forbidden", {}, None)
        mock_urlopen.side_effect = err
        
        ok = self.reporter.report_match_result("mid", 1, {})
        self.assertFalse(ok)

if __name__ == '__main__':
    unittest.main()
