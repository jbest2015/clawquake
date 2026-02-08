"""
Integration tests for the full match lifecycle:
  Queue → Matchmaker → ProcessManager → Results → ELO Update

Uses mock subprocesses to avoid needing a real game server.
"""

import sys
import os
import asyncio
import time
from unittest.mock import MagicMock, patch, AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))
sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only")
os.environ.setdefault("RCON_PASSWORD", "test-rcon-password")

from matchmaker import EloCalculator, MatchMaker
from process_manager import BotProcessManager, BotProcess, MatchProcessGroup
from models import QueueEntryDB, MatchDB, MatchParticipantDB, BotDB
from conftest import create_test_user, create_test_bot, queue_bot


# ── Process Manager Unit Tests ───────────────────────────────────

class TestBotProcessManager:

    def test_init(self):
        """ProcessManager initializes with default settings."""
        pm = BotProcessManager(
            agent_runner_path="/fake/path/agent_runner.py",
            orchestrator_url="http://localhost:8000",
            internal_secret="test-secret",
        )
        assert pm.agent_runner_path == "/fake/path/agent_runner.py"
        assert pm.orchestrator_url == "http://localhost:8000"
        assert pm._matches == {}

    def test_active_matches_empty(self):
        """No active matches initially."""
        pm = BotProcessManager(agent_runner_path="/fake/path")
        assert pm.active_matches() == []
        assert pm.active_match_count() == 0

    @patch("process_manager.subprocess.Popen")
    def test_launch_bot(self, mock_popen):
        """launch_bot spawns a subprocess and tracks it."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # still running
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        pm = BotProcessManager(
            agent_runner_path="/fake/agent_runner.py",
            orchestrator_url="http://localhost:8000",
            internal_secret="secret",
        )

        bot_proc = pm.launch_bot(
            match_id=1,
            bot_id=10,
            bot_name="TestBot",
            strategy_path="strategies/default.py",
            server_url="ws://localhost:27960",
            duration=120,
        )

        assert bot_proc.match_id == 1
        assert bot_proc.bot_id == 10
        assert bot_proc.bot_name == "TestBot"
        assert bot_proc.process is mock_proc
        assert not bot_proc.finished

        # Verify subprocess was called with correct args
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        assert "python" in call_args[0]
        assert "--strategy" in call_args
        assert "--name" in call_args
        assert "TestBot" in call_args
        assert "--match-id" in call_args
        assert "--bot-id" in call_args

    @patch("process_manager.subprocess.Popen")
    def test_launch_match(self, mock_popen):
        """launch_match spawns all bots for a match."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 100
        mock_popen.return_value = mock_proc

        pm = BotProcessManager(agent_runner_path="/fake/runner.py")

        bots = [
            {"bot_id": 1, "bot_name": "Bot1", "strategy_path": "s1.py"},
            {"bot_id": 2, "bot_name": "Bot2", "strategy_path": "s2.py"},
        ]
        group = pm.launch_match(
            match_id=42,
            bots=bots,
            server_url="ws://server:27960",
            duration=120,
        )

        assert group.match_id == 42
        assert len(group.bot_processes) == 2
        assert 1 in group.bot_processes
        assert 2 in group.bot_processes
        assert mock_popen.call_count == 2

    @patch("process_manager.subprocess.Popen")
    def test_check_match_running(self, mock_popen):
        """check_match reports running processes."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # still running
        mock_popen.return_value = mock_proc

        pm = BotProcessManager(agent_runner_path="/fake/runner.py")
        pm.launch_bot(1, 10, "Bot", "s.py", "ws://x", 60)

        status = pm.check_match(1)
        assert not status["all_finished"]
        assert 10 in status["bots"]
        assert not status["bots"][10]["finished"]

    @patch("process_manager.subprocess.Popen")
    def test_check_match_finished(self, mock_popen):
        """check_match detects finished processes."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # exited successfully
        mock_popen.return_value = mock_proc

        pm = BotProcessManager(agent_runner_path="/fake/runner.py")
        pm.launch_bot(1, 10, "Bot", "s.py", "ws://x", 60)

        status = pm.check_match(1)
        assert status["all_finished"]
        assert status["bots"][10]["finished"]
        assert status["bots"][10]["return_code"] == 0

    @patch("process_manager.subprocess.Popen")
    def test_check_match_not_found(self, mock_popen):
        """check_match returns finished for unknown match."""
        pm = BotProcessManager(agent_runner_path="/fake/runner.py")
        status = pm.check_match(999)
        assert status["all_finished"]
        assert "error" in status

    @patch("process_manager.subprocess.Popen")
    def test_kill_match(self, mock_popen):
        """kill_match terminates all processes."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # still running
        mock_proc.pid = 1234
        mock_popen.return_value = mock_proc

        pm = BotProcessManager(agent_runner_path="/fake/runner.py")
        pm.launch_bot(1, 10, "Bot1", "s.py", "ws://x", 60)
        pm.launch_bot(1, 20, "Bot2", "s.py", "ws://x", 60)

        pm.kill_match(1)

        # All processes should be marked finished
        status = pm.check_match(1)
        assert status["all_finished"]
        for bot_status in status["bots"].values():
            assert bot_status["finished"]
            assert bot_status["return_code"] == -1

    @patch("process_manager.subprocess.Popen")
    def test_kill_bot(self, mock_popen):
        """kill_bot terminates a single process."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        pm = BotProcessManager(agent_runner_path="/fake/runner.py")
        pm.launch_bot(1, 10, "Bot", "s.py", "ws://x", 60)

        pm.kill_bot(1, 10)

        bot = pm._matches[1].bot_processes[10]
        assert bot.finished
        assert bot.return_code == -1

    @patch("process_manager.subprocess.Popen")
    def test_cleanup_match(self, mock_popen):
        """cleanup_match removes tracking data."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        pm = BotProcessManager(agent_runner_path="/fake/runner.py")
        pm.launch_bot(1, 10, "Bot", "s.py", "ws://x", 60)
        assert 1 in pm._matches

        pm.cleanup_match(1)
        assert 1 not in pm._matches

    @patch("process_manager.subprocess.Popen")
    def test_is_match_timed_out(self, mock_popen):
        """Timeout detection based on duration + buffer."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        pm = BotProcessManager(agent_runner_path="/fake/runner.py")
        pm.launch_bot(1, 10, "Bot", "s.py", "ws://x", 60)

        # Just started — not timed out
        assert not pm.is_match_timed_out(1)

        # Fake the start time to be old
        pm._matches[1].started_at = time.time() - 200  # 200s ago
        assert pm.is_match_timed_out(1)  # 60 + 30 buffer = 90 < 200

    @patch("process_manager.subprocess.Popen")
    def test_active_matches(self, mock_popen):
        """active_matches returns info for all tracked matches."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        pm = BotProcessManager(agent_runner_path="/fake/runner.py")
        pm.launch_bot(1, 10, "Bot1", "s.py", "ws://x", 60)
        pm.launch_bot(2, 20, "Bot2", "s.py", "ws://y", 120)

        active = pm.active_matches()
        assert len(active) == 2
        match_ids = {m["match_id"] for m in active}
        assert match_ids == {1, 2}

    @patch("process_manager.subprocess.Popen")
    def test_active_match_count(self, mock_popen):
        """active_match_count counts only running matches."""
        mock_proc_running = MagicMock()
        mock_proc_running.poll.return_value = None

        mock_proc_done = MagicMock()
        mock_proc_done.poll.return_value = 0

        mock_popen.side_effect = [mock_proc_running, mock_proc_done]

        pm = BotProcessManager(agent_runner_path="/fake/runner.py")
        pm.launch_bot(1, 10, "Bot1", "s.py", "ws://x", 60)
        pm.launch_bot(2, 20, "Bot2", "s.py", "ws://y", 60)

        assert pm.active_match_count() == 1  # only match 1 is running


# ── Full Match Lifecycle Integration Tests ───────────────────────

class TestFullMatchLifecycle:

    def test_full_lifecycle(self, db, db_factory):
        """
        Full lifecycle: queue bots → matchmaker creates match → results →
        finalize → ELO updated.
        """
        user = create_test_user(db)
        bot1 = create_test_bot(db, "Alpha", user.id, elo=1000.0)
        bot2 = create_test_bot(db, "Bravo", user.id, elo=1000.0)

        # Step 1: Queue bots
        queue_bot(db, bot1.id, user.id)
        queue_bot(db, bot2.id, user.id)

        # Step 2: Matchmaker polls and creates match
        mm = MatchMaker(db_session_factory=db_factory)
        match_id = mm.poll_queue()
        assert match_id is not None

        # Step 3: Verify match created
        match = db.query(MatchDB).filter(MatchDB.id == match_id).first()
        assert match is not None
        assert match.ended_at is None

        # Step 4: Collect results (simulating agent_runner reports)
        mm.collect_result(match_id, bot1.id, kills=10, deaths=3)
        mm.collect_result(match_id, bot2.id, kills=3, deaths=10)

        # Step 5: Finalize match
        mm.finalize_match(match_id)

        # Step 6: Verify ELO updated
        db.expire_all()
        alpha = db.query(BotDB).filter(BotDB.id == bot1.id).first()
        bravo = db.query(BotDB).filter(BotDB.id == bot2.id).first()

        assert alpha.elo > 1000.0, f"Winner should gain ELO, got {alpha.elo}"
        assert bravo.elo < 1000.0, f"Loser should lose ELO, got {bravo.elo}"
        assert alpha.wins == 1
        assert bravo.losses == 1
        assert alpha.kills == 10
        assert bravo.deaths == 10

        # Step 7: Verify match finalized
        match = db.query(MatchDB).filter(MatchDB.id == match_id).first()
        assert match.ended_at is not None
        assert match.winner == "Alpha"

        # Step 8: Verify queue entries cleaned up
        entries = db.query(QueueEntryDB).all()
        assert all(e.status == "done" for e in entries)

    def test_elo_conservation_after_match(self, db, db_factory):
        """Total ELO should be conserved after a match."""
        user = create_test_user(db)
        bot1 = create_test_bot(db, "P1", user.id, elo=1200.0)
        bot2 = create_test_bot(db, "P2", user.id, elo=800.0)

        total_before = bot1.elo + bot2.elo

        e1 = queue_bot(db, bot1.id, user.id)
        e2 = queue_bot(db, bot2.id, user.id)

        mm = MatchMaker(db_session_factory=db_factory)
        match_id = mm.create_match(db, [e1, e2])
        mm.collect_result(match_id, bot1.id, kills=5, deaths=2)
        mm.collect_result(match_id, bot2.id, kills=2, deaths=5)
        mm.finalize_match(match_id)

        db.expire_all()
        p1 = db.query(BotDB).filter(BotDB.id == bot1.id).first()
        p2 = db.query(BotDB).filter(BotDB.id == bot2.id).first()

        total_after = p1.elo + p2.elo
        assert abs(total_after - total_before) < 0.1, (
            f"ELO not conserved: before={total_before}, after={total_after}"
        )

    def test_concurrent_matches(self, db, db_factory):
        """Multiple matches can be created and finalized independently."""
        user = create_test_user(db)

        # Create 4 bots for 2 matches
        bot1 = create_test_bot(db, "M1B1", user.id, elo=1000.0)
        bot2 = create_test_bot(db, "M1B2", user.id, elo=1000.0)
        bot3 = create_test_bot(db, "M2B1", user.id, elo=1000.0)
        bot4 = create_test_bot(db, "M2B2", user.id, elo=1000.0)

        mm = MatchMaker(db_session_factory=db_factory)

        # Create match 1
        e1 = queue_bot(db, bot1.id, user.id)
        e2 = queue_bot(db, bot2.id, user.id)
        match1_id = mm.create_match(db, [e1, e2], map_name="q3dm6")

        # Create match 2
        e3 = queue_bot(db, bot3.id, user.id)
        e4 = queue_bot(db, bot4.id, user.id)
        match2_id = mm.create_match(db, [e3, e4], map_name="q3dm17")

        assert match1_id != match2_id

        # Finalize match 2 first (out of order)
        mm.collect_result(match2_id, bot3.id, kills=8, deaths=4)
        mm.collect_result(match2_id, bot4.id, kills=4, deaths=8)
        mm.finalize_match(match2_id)

        # Match 1 should still be open
        db.expire_all()
        m1 = db.query(MatchDB).filter(MatchDB.id == match1_id).first()
        m2 = db.query(MatchDB).filter(MatchDB.id == match2_id).first()
        assert m1.ended_at is None
        assert m2.ended_at is not None

        # Now finalize match 1
        mm.collect_result(match1_id, bot1.id, kills=3, deaths=7)
        mm.collect_result(match1_id, bot2.id, kills=7, deaths=3)
        mm.finalize_match(match1_id)

        db.expire_all()
        m1 = db.query(MatchDB).filter(MatchDB.id == match1_id).first()
        assert m1.ended_at is not None
        assert m1.winner == "M1B2"

    def test_match_with_tie(self, db, db_factory):
        """Tied match should still finalize correctly."""
        user = create_test_user(db)
        bot1 = create_test_bot(db, "Tied1", user.id, elo=1000.0)
        bot2 = create_test_bot(db, "Tied2", user.id, elo=1000.0)

        e1 = queue_bot(db, bot1.id, user.id)
        e2 = queue_bot(db, bot2.id, user.id)

        mm = MatchMaker(db_session_factory=db_factory)
        match_id = mm.create_match(db, [e1, e2])

        # Equal scores
        mm.collect_result(match_id, bot1.id, kills=5, deaths=5)
        mm.collect_result(match_id, bot2.id, kills=5, deaths=5)
        mm.finalize_match(match_id)

        db.expire_all()
        t1 = db.query(BotDB).filter(BotDB.id == bot1.id).first()
        t2 = db.query(BotDB).filter(BotDB.id == bot2.id).first()

        # ELO should be unchanged for equal-rated tied match
        assert abs(t1.elo - 1000.0) < 0.01
        assert abs(t2.elo - 1000.0) < 0.01


# ── Async Wait Tests ─────────────────────────────────────────────

class TestAsyncWait:

    @patch("process_manager.subprocess.Popen")
    def test_wait_for_match_immediate(self, mock_popen):
        """wait_for_match returns immediately when processes already done."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # already finished
        mock_popen.return_value = mock_proc

        pm = BotProcessManager(agent_runner_path="/fake/runner.py")
        pm.launch_bot(1, 10, "Bot", "s.py", "ws://x", 60)

        result = asyncio.get_event_loop().run_until_complete(
            pm.wait_for_match(1, poll_interval=0.01)
        )
        assert result["all_finished"]
