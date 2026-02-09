
import unittest
from unittest.mock import Mock, MagicMock
from tournament.bracket import TournamentBracket
from orchestrator.models import (
    TournamentDB, TournamentParticipantDB, TournamentMatchDB, BotDB
)

class TestTournamentBracket(unittest.TestCase):
    
    def setUp(self):
        self.db = MagicMock()
        self.bracket = TournamentBracket(self.db)
        
    def test_create_tournament(self):
        t = self.bracket.create_tournament("Spring Cup", "single_elim")
        self.db.add.assert_called()
        args = self.db.add.call_args[0][0]
        self.assertIsInstance(args, TournamentDB)
        self.assertEqual(args.name, "Spring Cup")
        self.assertEqual(args.format, "single_elim")
        self.assertEqual(args.status, "pending")
        
    def test_add_participant(self):
        # Mock existing check
        self.db.query().filter_by().first.return_value = None
        
        ok = self.bracket.add_participant(1, 101)
        self.assertTrue(ok)
        self.db.add.assert_called()
        args = self.db.add.call_args[0][0]
        self.assertIsInstance(args, TournamentParticipantDB)
        self.assertEqual(args.tournament_id, 1)
        self.assertEqual(args.bot_id, 101)
        
    def test_start_tournament_single_elim(self):
        t_mock = TournamentDB(id=1, status="pending")
        self.db.query().filter_by().first.return_value = t_mock
        
        # 4 participants
        p_list = [
            TournamentParticipantDB(tournament_id=1, bot_id=10),
            TournamentParticipantDB(tournament_id=1, bot_id=11),
            TournamentParticipantDB(tournament_id=1, bot_id=12),
            TournamentParticipantDB(tournament_id=1, bot_id=13)
        ]
        self.db.query().filter_by().all.return_value = p_list
        
        # Mock BotDB lookups for ELO
        def query_side_effect(model):
            m = MagicMock()
            if model == BotDB:
                # Returns a mock query object, which needs filter_by().first()
                q = MagicMock()
                q.filter_by.return_value.first.return_value = BotDB(elo=1500)
                return q
            elif model == TournamentParticipantDB:
                q = MagicMock()
                q.filter_by.return_value.all.return_value = p_list
                return q
            elif model == TournamentDB:
                 q = MagicMock()
                 q.filter_by.return_value.first.return_value = t_mock
                 return q
            return m
            
        self.db.query.side_effect = query_side_effect
        
        # We need to mock _generate_future_rounds since it does complex DB queries
        self.bracket._generate_future_rounds = Mock()
        
        ok = self.bracket.start_tournament(1)
        self.assertTrue(ok)
        self.assertEqual(t_mock.status, "active")
        self.assertEqual(t_mock.current_round, 1)
        
        # Should create 2 matches for Round 1 (4 players -> 2 matches)
        # 4 add calls: (p1, p2, p3, p4 seeding updates? No, seeds updated on objects)
        # Matches added
        # We expect add() calls for Matches.
        # Actually seeding modifies objects attached to session, doesn't call add().
        # So we look for TournamentMatchDB adds.
        
        match_adds = [
            c[0][0] for c in self.db.add.call_args_list 
            if isinstance(c[0][0], TournamentMatchDB)
        ]
        self.assertEqual(len(match_adds), 2)
        
    def test_record_result_advancement(self):
        # Match 1: P1 vs P2 -> Winner P1. Next match is ID 3.
        m1 = TournamentMatchDB(
            id=1, tournament_id=1, round_num=1, 
            player1_bot_id=10, player2_bot_id=11, 
            next_match_id=3
        )
        
        m3 = TournamentMatchDB(
            id=3, tournament_id=1, round_num=2,
            player1_bot_id=None, player2_bot_id=None
        )
        
        def get_side_effect(mid):
            if mid == 3: return m3
            return None
            
        self.db.query().filter_by().first.return_value = m1
        self.db.query().get.side_effect = get_side_effect
        
        self.bracket.record_result(1, 1, 10)
        
        self.assertEqual(m1.winner_bot_id, 10)
        self.assertEqual(m3.player1_bot_id, 10)

if __name__ == '__main__':
    unittest.main()
