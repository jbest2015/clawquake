"""
Tests for the matchmaker engine: ELO calculation, queue polling, match lifecycle.
"""

import sys
import os

# Add orchestrator and tests dirs to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))
sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only")
os.environ.setdefault("RCON_PASSWORD", "test-rcon-password")

from matchmaker import EloCalculator, MatchMaker
from models import QueueEntryDB, MatchDB, MatchParticipantDB, BotDB

# Import helpers from conftest (pytest auto-loads fixtures, but we need the functions)
from conftest import create_test_user, create_test_bot, queue_bot


# ── ELO Calculator Tests ────────────────────────────────────────

class TestEloCalculator:

    def test_elo_calculation_winner_gains(self):
        """Winner's ELO should increase, loser's should decrease."""
        new_winner, new_loser = EloCalculator.calculate(1000.0, 1000.0)
        assert new_winner > 1000.0
        assert new_loser < 1000.0

    def test_elo_calculation_symmetric(self):
        """Total ELO should be conserved (winner gain = loser loss)."""
        new_winner, new_loser = EloCalculator.calculate(1000.0, 1000.0)
        total_before = 2000.0
        total_after = new_winner + new_loser
        assert abs(total_after - total_before) < 0.01

    def test_elo_calculation_upset(self):
        """Lower-rated winner should gain more than higher-rated winner would."""
        # Normal: higher rated wins
        normal_winner, _ = EloCalculator.calculate(1200.0, 1000.0)
        normal_gain = normal_winner - 1200.0

        # Upset: lower rated wins
        upset_winner, _ = EloCalculator.calculate(1000.0, 1200.0)
        upset_gain = upset_winner - 1000.0

        # Upset should produce a bigger gain
        assert upset_gain > normal_gain

    def test_elo_equal_ratings_split(self):
        """Equal ratings: winner gets +16, loser gets -16 (K=32)."""
        new_winner, new_loser = EloCalculator.calculate(1000.0, 1000.0, k=32)
        assert abs(new_winner - 1016.0) < 0.01
        assert abs(new_loser - 984.0) < 0.01

    def test_elo_ffa_basic(self):
        """FFA calculation with 3 players."""
        participants = [
            {"bot_id": 1, "elo": 1000.0, "score": 5},
            {"bot_id": 2, "elo": 1000.0, "score": 3},
            {"bot_id": 3, "elo": 1000.0, "score": 1},
        ]
        results = EloCalculator.calculate_ffa(participants)

        # Highest scorer should gain, lowest should lose
        p1 = next(r for r in results if r["bot_id"] == 1)
        p3 = next(r for r in results if r["bot_id"] == 3)
        assert p1["elo_change"] > 0
        assert p3["elo_change"] < 0

    def test_elo_ffa_single_player(self):
        """Single player FFA: no ELO change."""
        participants = [{"bot_id": 1, "elo": 1000.0, "score": 5}]
        results = EloCalculator.calculate_ffa(participants)
        assert results[0]["elo_change"] == 0.0


# ── MatchMaker Queue Tests ──────────────────────────────────────

class TestMatchMakerQueue:

    def test_queue_poll_no_bots(self, db, db_factory):
        """Empty queue should return None (no match created)."""
        mm = MatchMaker(db_session_factory=db_factory)
        result = mm.poll_queue()
        assert result is None

    def test_queue_poll_one_bot(self, db, db_factory):
        """Single bot in queue should not trigger a match."""
        user = create_test_user(db)
        bot = create_test_bot(db, "SoloBot", user.id)
        queue_bot(db, bot.id, user.id)

        mm = MatchMaker(db_session_factory=db_factory)
        result = mm.poll_queue()
        assert result is None

    def test_queue_poll_two_bots_creates_match(self, db, db_factory):
        """Two bots in queue should create a match."""
        user = create_test_user(db)
        bot1 = create_test_bot(db, "Bot1", user.id)
        bot2 = create_test_bot(db, "Bot2", user.id)
        queue_bot(db, bot1.id, user.id)
        queue_bot(db, bot2.id, user.id)

        mm = MatchMaker(db_session_factory=db_factory)
        match_id = mm.poll_queue()

        assert match_id is not None

        # Verify match exists in DB
        match = db.query(MatchDB).filter(MatchDB.id == match_id).first()
        assert match is not None
        assert match.map_name == "q3dm17"

        # Verify participants
        participants = (
            db.query(MatchParticipantDB)
            .filter(MatchParticipantDB.match_id == match_id)
            .all()
        )
        assert len(participants) == 2

        # Verify queue entries updated
        entries = db.query(QueueEntryDB).all()
        assert all(e.status == "matched" for e in entries)


# ── MatchMaker Match Lifecycle Tests ─────────────────────────────

class TestMatchMakerLifecycle:

    def test_create_match_db_record(self, db, db_factory):
        """create_match should create MatchDB + MatchParticipantDB records."""
        user = create_test_user(db)
        bot1 = create_test_bot(db, "Bot1", user.id, elo=1100.0)
        bot2 = create_test_bot(db, "Bot2", user.id, elo=900.0)
        entry1 = queue_bot(db, bot1.id, user.id)
        entry2 = queue_bot(db, bot2.id, user.id)

        mm = MatchMaker(db_session_factory=db_factory)
        match_id = mm.create_match(db, [entry1, entry2], map_name="q3dm6")

        match = db.query(MatchDB).filter(MatchDB.id == match_id).first()
        assert match.map_name == "q3dm6"

        parts = (
            db.query(MatchParticipantDB)
            .filter(MatchParticipantDB.match_id == match_id)
            .all()
        )
        assert len(parts) == 2

        # ELO before should be recorded
        elos = {p.bot_id: p.elo_before for p in parts}
        assert elos[bot1.id] == 1100.0
        assert elos[bot2.id] == 900.0

    def test_collect_result(self, db, db_factory):
        """collect_result should update participant stats."""
        user = create_test_user(db)
        bot1 = create_test_bot(db, "Bot1", user.id)
        bot2 = create_test_bot(db, "Bot2", user.id)
        entry1 = queue_bot(db, bot1.id, user.id)
        entry2 = queue_bot(db, bot2.id, user.id)

        mm = MatchMaker(db_session_factory=db_factory)
        match_id = mm.create_match(db, [entry1, entry2])

        mm.collect_result(match_id, bot1.id, kills=5, deaths=2)

        # Verify participant updated
        part = (
            db.query(MatchParticipantDB)
            .filter(
                MatchParticipantDB.match_id == match_id,
                MatchParticipantDB.bot_id == bot1.id,
            )
            .first()
        )
        assert part.kills == 5
        assert part.deaths == 2
        assert part.score == 3  # kills - deaths

    def test_finalize_match_updates_elo(self, db, db_factory):
        """finalize_match should calculate ELO and update BotDB."""
        user = create_test_user(db)
        bot1 = create_test_bot(db, "Winner", user.id, elo=1000.0)
        bot2 = create_test_bot(db, "Loser", user.id, elo=1000.0)
        entry1 = queue_bot(db, bot1.id, user.id)
        entry2 = queue_bot(db, bot2.id, user.id)

        mm = MatchMaker(db_session_factory=db_factory)
        match_id = mm.create_match(db, [entry1, entry2])

        # Bot1 wins with 5 kills
        mm.collect_result(match_id, bot1.id, kills=5, deaths=1)
        mm.collect_result(match_id, bot2.id, kills=1, deaths=5)

        mm.finalize_match(match_id)

        # Refresh from DB
        db.expire_all()
        winner = db.query(BotDB).filter(BotDB.id == bot1.id).first()
        loser = db.query(BotDB).filter(BotDB.id == bot2.id).first()

        assert winner.elo > 1000.0, f"Winner ELO should increase, got {winner.elo}"
        assert loser.elo < 1000.0, f"Loser ELO should decrease, got {loser.elo}"
        assert winner.wins == 1
        assert loser.losses == 1

    def test_finalize_match_updates_bot_stats(self, db, db_factory):
        """finalize_match should accumulate kills/deaths in BotDB."""
        user = create_test_user(db)
        bot1 = create_test_bot(db, "StatsBot", user.id)
        bot2 = create_test_bot(db, "FodderBot", user.id)
        entry1 = queue_bot(db, bot1.id, user.id)
        entry2 = queue_bot(db, bot2.id, user.id)

        mm = MatchMaker(db_session_factory=db_factory)
        match_id = mm.create_match(db, [entry1, entry2])

        mm.collect_result(match_id, bot1.id, kills=7, deaths=3)
        mm.collect_result(match_id, bot2.id, kills=3, deaths=7)

        mm.finalize_match(match_id)

        db.expire_all()
        stats_bot = db.query(BotDB).filter(BotDB.id == bot1.id).first()
        assert stats_bot.kills == 7
        assert stats_bot.deaths == 3

    def test_finalize_match_marks_ended(self, db, db_factory):
        """finalize_match should set ended_at and winner on MatchDB."""
        user = create_test_user(db)
        bot1 = create_test_bot(db, "Alpha", user.id)
        bot2 = create_test_bot(db, "Beta", user.id)
        entry1 = queue_bot(db, bot1.id, user.id)
        entry2 = queue_bot(db, bot2.id, user.id)

        mm = MatchMaker(db_session_factory=db_factory)
        match_id = mm.create_match(db, [entry1, entry2])

        mm.collect_result(match_id, bot1.id, kills=10, deaths=0)
        mm.collect_result(match_id, bot2.id, kills=0, deaths=10)

        mm.finalize_match(match_id)

        db.expire_all()
        match = db.query(MatchDB).filter(MatchDB.id == match_id).first()
        assert match.ended_at is not None
        assert match.winner == "Alpha"
