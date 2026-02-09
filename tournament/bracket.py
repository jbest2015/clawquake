
"""
Tournament bracket system for ClawQuake.

Handles:
- Single elimination bracket generation
- Seeding by ELO
- Match progression
- Bye handling for non-power-of-2 participant counts
"""

import math
import logging
from datetime import datetime
from sqlalchemy import func
try:
    from orchestrator.models import (
        TournamentDB, TournamentParticipantDB, TournamentMatchDB, BotDB
    )
except ModuleNotFoundError:
    from models import (
        TournamentDB, TournamentParticipantDB, TournamentMatchDB, BotDB
    )

logger = logging.getLogger('clawquake.tournament')

class TournamentBracket:
    
    def __init__(self, db_session):
        self.db = db_session
        
    def create_tournament(self, name, format="single_elim"):
        """Create a new pending tournament."""
        t = TournamentDB(name=name, format=format, status="pending")
        self.db.add(t)
        self.db.commit()
        return t

    def add_participant(self, tournament_id, bot_id):
        """Add a bot to the tournament."""
        # Check if already joined
        existing = self.db.query(TournamentParticipantDB).filter_by(
            tournament_id=tournament_id, bot_id=bot_id
        ).first()
        if existing:
            return False
            
        p = TournamentParticipantDB(tournament_id=tournament_id, bot_id=bot_id)
        self.db.add(p)
        self.db.commit()
        return True

    def start_tournament(self, tournament_id, seed_by_elo=True):
        """Seed players and generate the first round matches."""
        t = self.db.query(TournamentDB).filter_by(id=tournament_id).first()
        if not t or t.status != "pending":
            return False
            
        participants = self.db.query(TournamentParticipantDB).filter_by(
            tournament_id=tournament_id
        ).all()
        
        count = len(participants)
        if count < 2:
            return False # Need at least 2 players
            
        # 1. Seeding
        if seed_by_elo:
            # Fetch bot ELOs
            bots = []
            for p in participants:
                bot = self.db.query(BotDB).filter_by(id=p.bot_id).first()
                bots.append((p, bot.elo if bot else 1000.0))
            
            # Sort high ELO first (seed 1)
            bots.sort(key=lambda x: x[1], reverse=True)
            
            # Assign seeds
            ordered_participants = []
            for i, (p, elo) in enumerate(bots):
                p.seed = i + 1
                ordered_participants.append(p)
        else:
            # Random shuffle or insert order
            ordered_participants = participants
            for i, p in enumerate(ordered_participants):
                p.seed = i + 1

        self.db.commit()

        # 2. Bracket Generation (Single Elim)
        # Power of 2 Size
        bracket_size = 2 ** math.ceil(math.log2(count))
        
        # Generate match pairings for Round 1
        # Standard seed pairing: 1 vs N, 2 vs N-1, etc.
        pairings = self._generate_pairings(ordered_participants, bracket_size)
        
        # Create Round 1 matches
        for i, (p1, p2) in enumerate(pairings):
            match = TournamentMatchDB(
                tournament_id=tournament_id,
                round_num=1,
                match_num=i + 1,
                player1_bot_id=p1.bot_id if p1 else None,
                player2_bot_id=p2.bot_id if p2 else None,
                winner_bot_id=p1.bot_id if not p2 else (p2.bot_id if not p1 else None)
            )
            # Handle byes immediately
            if not p2 and p1:
                match.winner_bot_id = p1.bot_id
            elif not p1 and p2: # Should not happen with standard seeding
                match.winner_bot_id = p2.bot_id
                
            self.db.add(match)
            
        t.status = "active"
        t.started_at = datetime.utcnow()
        t.current_round = 1
        self.db.commit()
        
        self._generate_future_rounds(tournament_id, bracket_size)
        return True

    def _generate_pairings(self, participants, bracket_size):
        """Generate first round pairings with Byes (None)."""
        # Simple folding method for standard bracket
        # 1 vs 8, 4 vs 5, 2 vs 7, 3 vs 6
        # Actually standard visualization order is different, but logic is:
        # Match N: Seed X vs Seed (Size+1 - X)
        
        seeds = [None] * bracket_size
        for p in participants:
            seeds[p.seed - 1] = p
            
        # Recursive pair generation for proper bracket order
        # [1, 8, 4, 5, 2, 7, 3, 6]
        round_seeds = self._get_bracket_order(bracket_size)
        
        pairings = []
        for i in range(0, len(round_seeds), 2):
            s1_idx = round_seeds[i] - 1
            s2_idx = round_seeds[i+1] - 1
            p1 = seeds[s1_idx] if s1_idx < len(seeds) else None
            p2 = seeds[s2_idx] if s2_idx < len(seeds) else None
            pairings.append((p1, p2))
            
        return pairings

    def _get_bracket_order(self, num_players):
        """Returns valid seeding order for a bracket of size num_players."""
        rounds = math.log2(num_players)
        pl = [1, 2]
        for i in range(int(rounds) - 1):
            pl = next_level(pl)
        return pl

    def _generate_future_rounds(self, tournament_id, bracket_size):
        """Pre-generate empty match slots for rounds 2+."""
        num_matches = bracket_size // 2
        current_matches = num_matches
        round_num = 2
        
        previous_round_matches = self.db.query(TournamentMatchDB).filter_by(
            tournament_id=tournament_id, round_num=1
        ).order_by(TournamentMatchDB.match_num).all()
        
        prev_matches = previous_round_matches
        
        while current_matches > 1:
            current_matches //= 2
            new_matches = []
            for i in range(current_matches):
                m = TournamentMatchDB(
                    tournament_id=tournament_id,
                    round_num=round_num,
                    match_num=i + 1,
                    player1_bot_id=None,
                    player2_bot_id=None
                )
                self.db.add(m)
                self.db.flush() # Need ID
                new_matches.append(m)
                
                # Link previous matches to this one
                # Previous match 2*i and 2*i+1 feed into this match
                if len(prev_matches) > 2*i:
                    prev_matches[2*i].next_match_id = m.id
                if len(prev_matches) > 2*i + 1:
                    prev_matches[2*i+1].next_match_id = m.id
                    
            prev_matches = new_matches
            round_num += 1
            
        self.db.commit()

    def record_result(self, tournament_id, match_id, winner_bot_id):
        """Record winner of a tournament match and advance bracket."""
        match = self.db.query(TournamentMatchDB).filter_by(
            tournament_id=tournament_id, id=match_id
        ).first()
        
        if not match or match.winner_bot_id:
            return None # Already finished or invalid

        match.winner_bot_id = winner_bot_id
        self.db.commit()
        
        # Advance to next match
        if match.next_match_id:
            next_match = self.db.query(TournamentMatchDB).get(match.next_match_id)
            if not next_match.player1_bot_id:
                next_match.player1_bot_id = winner_bot_id
            else:
                next_match.player2_bot_id = winner_bot_id
            self.db.commit()
        else:
            # No next match -> Tournament Winner!
            t = self.db.query(TournamentDB).get(tournament_id)
            t.winner_bot_id = winner_bot_id
            t.status = "completed"
            t.ended_at = datetime.utcnow()
            self.db.commit()

    def get_bracket(self, tournament_id):
        """Return full bracket data."""
        matches = self.db.query(TournamentMatchDB).filter_by(
            tournament_id=tournament_id
        ).order_by(TournamentMatchDB.round_num, TournamentMatchDB.match_num).all()
        
        # Structure by round
        rounds = {}
        for m in matches:
            if m.round_num not in rounds:
                rounds[m.round_num] = []
            rounds[m.round_num].append(m)
            
        return rounds

# Helper for bracket seeding order
def next_level(matches):
    """
    Given a list of matches (seeds), generate the next round's seeding.
    e.g. [1, 2] -> [1, 4, 2, 3] (if next power is 4)
    """
    next_matches = []
    high = len(matches) * 2 + 1
    for m in matches:
        next_matches.append(m)
        next_matches.append(high - m)
    return next_matches
