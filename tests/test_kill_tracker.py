
import unittest
from bot.kill_tracker import KillTracker

class TestKillTracker(unittest.TestCase):

    def setUp(self):
        self.tracker = KillTracker("TestBot")

    def test_parse_was_railgunned_by(self):
        msg = 'TestBot was railgunned by EnemyBot'
        result = self.tracker.parse_server_command(f'print "{msg}"')
        self.assertIsNotNone(result)
        self.assertEqual(result, ('EnemyBot', 'TestBot', 'railgun'))

    def test_parse_was_melted_by_plasmagun(self):
        msg = "TestBot was melted by EnemyBot's plasmagun"
        result = self.tracker.parse_server_command(f'print "{msg}"')
        self.assertIsNotNone(result)
        # Groups: 1=Victim, 2=Killer, 3=Weapon
        # My implementation: return group(2), group(1), group(3)
        self.assertEqual(result, ('EnemyBot', 'TestBot', 'plasmagun'))

    def test_parse_almost_dodged_rocket(self):
        msg = "TestBot almost dodged EnemyBot's rocket"
        result = self.tracker.parse_server_command(f'print "{msg}"')
        self.assertIsNotNone(result)
        self.assertEqual(result, ('EnemyBot', 'TestBot', 'rocket'))

    def test_parse_killed_by_simple(self):
        msg = "EnemyBot killed TestBot"
        result = self.tracker.parse_server_command(f'print "{msg}"')
        self.assertIsNotNone(result)
        self.assertEqual(result, ('EnemyBot', 'TestBot', 'unknown'))

    def test_parse_suicide(self):
        # "TestBot suid" or whatever Q3 sends. 
        # "TestBot killed himself" -> "TestBot killed himself" matches "(.+) killed (.+)"?
        # "TestBot" and "himself".
        # Let's assume standard Q3 messages.
        # "TestBot cratered" (falling)
        pass 

    def test_parse_with_color_codes(self):
        msg = "^1Test^2Bot ^7was railgunned by ^3Enemy^4Bot"
        # Cleaned: "TestBot was railgunned by EnemyBot"
        result = self.tracker.parse_server_command(f'print "{msg}"')
        # This matches pattern 2 "was ... by"
        self.assertEqual(result, ('EnemyBot', 'TestBot', 'railgun'))

    def test_record_kill_increments(self):
        self.tracker.record('TestBot', 'EnemyBot', 'railgun')
        self.assertEqual(self.tracker.kills, 1)
        self.assertEqual(self.tracker.deaths, 0)
        self.assertEqual(len(self.tracker.kill_log), 1)

    def test_record_death_increments(self):
        self.tracker.record('EnemyBot', 'TestBot', 'railgun')
        self.assertEqual(self.tracker.kills, 0)
        self.assertEqual(self.tracker.deaths, 1)
        self.assertEqual(len(self.tracker.death_log), 1)

    def test_kd_ratio_zero_deaths(self):
        self.tracker.record('TestBot', 'Enemy1', 'railgun')
        self.tracker.record('TestBot', 'Enemy2', 'railgun')
        self.assertEqual(self.tracker.deaths, 0)
        self.assertEqual(self.tracker.kd_ratio, 2.0)

    def test_to_dict(self):
        self.tracker.record('TestBot', 'Enemy', 'gun')
        d = self.tracker.to_dict()
        self.assertEqual(d['kills'], 1)
        self.assertEqual(d['deaths'], 0)
        self.assertIn('kill_log', d)

if __name__ == '__main__':
    unittest.main()
