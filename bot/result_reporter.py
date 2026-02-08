"""
ResultReporter module for ClawQuake match reporting.

Handles sending match statistics to the orchestrator API after a match completes.
"""

import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger('clawquake.result_reporter')

class ResultReporter:
    """
    Submits match results to the central orchestrator.
    
    Handles API communication, authentication via internal secret, and error handling.
    """

    def __init__(self, orchestrator_url, internal_secret):
        self.orchestrator_url = orchestrator_url.rstrip('/')
        self.internal_secret = internal_secret

    def report_match_result(self, match_id, bot_id, stats):
        """
        Report match results for a specific bot and match ID.
        
        Args:
            match_id (str): The unique ID of the match.
            bot_id (int): The database ID of the bot.
            stats (dict): The statistics dictionary (kills, deaths, logs, etc.).
            
        Returns:
            bool: True if successful, False otherwise.
        """
        url = f"{self.orchestrator_url}/api/internal/match/report"
        
        payload = {
            "match_id": match_id,
            "bot_id": bot_id,
            "stats": stats
        }
        
        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, method='POST')
            req.add_header('Content-Type', 'application/json')
            req.add_header('X-Internal-Secret', self.internal_secret)
            
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    logger.info(f"Match results reported successfully for match {match_id}, bot {bot_id}")
                    return True
                else:
                    logger.error(f"Failed to report results: HTTP {response.status}")
                    return False
                    
        except urllib.error.HTTPError as e:
            logger.error(f"HTTP Error reporting results: {e.code} - {e.reason}")
            # Try to read error body
            try:
                error_body = e.read().decode('utf-8')
                logger.error(f"Error body: {error_body}")
            except:
                pass
            return False
            
        except urllib.error.URLError as e:
            logger.error(f"Network Error reporting results: {e.reason}")
            return False
            
        except Exception as e:
            logger.error(f"Unexpected error reporting results: {e}")
            return False
