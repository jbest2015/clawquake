"""
End-to-end tests for ClawQuake platform.

Covers the full user journey:
  register → login → create API key → register bot → join queue →
  matchmaker creates match → results reported → ELO updated →
  leaderboard reflects changes
"""

import os
import sys
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only")
os.environ.setdefault("RCON_PASSWORD", "test-rcon-password")
os.environ.setdefault("INTERNAL_SECRET", "test-internal-secret")

from auth import get_db as auth_get_db
from main import app, INTERNAL_SECRET
from main import get_db as main_get_db
from models import Base, BotDB, MatchDB, MatchParticipantDB, QueueEntryDB, UserDB
from matchmaker import MatchMaker, EloCalculator
from routes_bots import get_db as bots_get_db
from routes_keys import get_db as keys_get_db
from routes_queue import get_db as queue_get_db


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_overrides():
    """Ensure dependency overrides are clean before and after each test."""
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def e2e_env():
    """Full E2E environment: TestClient + direct DB access."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[auth_get_db] = override_get_db
    app.dependency_overrides[main_get_db] = override_get_db
    app.dependency_overrides[bots_get_db] = override_get_db
    app.dependency_overrides[keys_get_db] = override_get_db
    app.dependency_overrides[queue_get_db] = override_get_db

    with TestClient(app) as client:
        yield {
            "client": client,
            "session_factory": TestingSession,
            "engine": engine,
        }

    app.dependency_overrides.clear()


# ── Helper Functions ──────────────────────────────────────────

def _register(client, username, email):
    res = client.post("/api/auth/register", json={
        "username": username, "email": email, "password": "testpass123",
    })
    assert res.status_code == 200, f"Register failed: {res.text}"
    return res.json()["access_token"]


def _login(client, username):
    res = client.post("/api/auth/login", json={
        "username": username, "password": "testpass123",
    })
    assert res.status_code == 200, f"Login failed: {res.text}"
    return res.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _apikey_header(key):
    return {"X-API-Key": key}


def _create_key(client, token, name="default"):
    res = client.post("/api/keys", json={"name": name}, headers=_auth(token))
    assert res.status_code == 200
    return res.json()


def _create_bot(client, token_or_headers, name):
    headers = token_or_headers if isinstance(token_or_headers, dict) else _auth(token_or_headers)
    res = client.post("/api/bots", json={"name": name}, headers=headers)
    assert res.status_code == 200
    return res.json()


def _join_queue(client, token_or_headers, bot_id):
    headers = token_or_headers if isinstance(token_or_headers, dict) else _auth(token_or_headers)
    res = client.post("/api/queue/join", json={"bot_id": bot_id}, headers=headers)
    assert res.status_code == 200
    return res.json()


def _internal_report(client, match_id, bot_id, bot_name, kills, deaths):
    """Simulate agent_runner reporting match results."""
    res = client.post("/api/internal/match/report", json={
        "match_id": match_id,
        "bot_id": bot_id,
        "bot_name": bot_name,
        "kills": kills,
        "deaths": deaths,
        "duration_seconds": 120.0,
        "strategy_name": "test",
        "strategy_version": "1.0",
    }, headers={"X-Internal-Secret": os.environ.get("INTERNAL_SECRET", "test-internal-secret")})
    return res


# ── E2E Test: Full User Journey ──────────────────────────────

class TestFullUserJourney:
    """Complete flow: register → bot → queue → match → ELO."""

    def test_register_login_get_me(self, e2e_env):
        c = e2e_env["client"]
        token = _register(c, "alice", "alice@test.com")

        # Verify /me works
        res = c.get("/api/auth/me", headers=_auth(token))
        assert res.status_code == 200
        me = res.json()
        assert me["username"] == "alice"
        assert me["email"] == "alice@test.com"
        assert me["is_admin"] is False

        # Login works
        token2 = _login(c, "alice")
        res2 = c.get("/api/auth/me", headers=_auth(token2))
        assert res2.status_code == 200
        assert res2.json()["username"] == "alice"

    def test_duplicate_register_fails(self, e2e_env):
        c = e2e_env["client"]
        _register(c, "bob", "bob@test.com")

        # Same username
        res = c.post("/api/auth/register", json={
            "username": "bob", "email": "bob2@test.com", "password": "test",
        })
        assert res.status_code == 400

        # Same email
        res = c.post("/api/auth/register", json={
            "username": "bob2", "email": "bob@test.com", "password": "test",
        })
        assert res.status_code == 400

    def test_bad_login(self, e2e_env):
        c = e2e_env["client"]
        _register(c, "carl", "carl@test.com")
        res = c.post("/api/auth/login", json={
            "username": "carl", "password": "wrong",
        })
        assert res.status_code == 401


class TestApiKeyWorkflow:
    """API key creation, usage, and revocation."""

    def test_create_and_use_api_key(self, e2e_env):
        c = e2e_env["client"]
        token = _register(c, "dina", "dina@test.com")

        # Create a bot via JWT
        bot = _create_bot(c, token, "DinaBot")

        # Create API key
        key_data = _create_key(c, token, "my-agent")
        assert key_data["key"].startswith("cq_")
        assert key_data["name"] == "my-agent"
        raw_key = key_data["key"]

        # Use API key to list bots
        res = c.get("/api/bots", headers=_apikey_header(raw_key))
        assert res.status_code == 200
        assert len(res.json()) == 1
        assert res.json()[0]["name"] == "DinaBot"

    def test_revoke_api_key(self, e2e_env):
        c = e2e_env["client"]
        token = _register(c, "eve", "eve@test.com")

        key_data = _create_key(c, token, "temp")
        raw_key = key_data["key"]

        # Revoke it
        res = c.delete(f"/api/keys/{key_data['id']}", headers=_auth(token))
        assert res.status_code == 200
        assert res.json()["deleted"] is True

        # Can no longer use it
        res = c.get("/api/bots", headers=_apikey_header(raw_key))
        assert res.status_code == 401

    def test_list_keys_hides_full_key(self, e2e_env):
        c = e2e_env["client"]
        token = _register(c, "faye", "faye@test.com")

        _create_key(c, token, "k1")
        _create_key(c, token, "k2")

        res = c.get("/api/keys", headers=_auth(token))
        assert res.status_code == 200
        keys = res.json()
        assert len(keys) == 2
        for k in keys:
            # Full key is never returned in list
            assert "key" not in k
            assert k["key_prefix"].startswith("cq_")


class TestBotRegistration:
    """Bot registration and management."""

    def test_register_and_list_bots(self, e2e_env):
        c = e2e_env["client"]
        token = _register(c, "greg", "greg@test.com")

        b1 = _create_bot(c, token, "Alpha")
        b2 = _create_bot(c, token, "Beta")

        res = c.get("/api/bots", headers=_auth(token))
        assert res.status_code == 200
        names = {b["name"] for b in res.json()}
        assert names == {"Alpha", "Beta"}

    def test_bot_isolation_between_users(self, e2e_env):
        c = e2e_env["client"]
        t1 = _register(c, "hank", "hank@test.com")
        t2 = _register(c, "ivy", "ivy@test.com")

        _create_bot(c, t1, "HankBot")
        _create_bot(c, t2, "IvyBot")

        # Each user sees only their bots
        r1 = c.get("/api/bots", headers=_auth(t1))
        r2 = c.get("/api/bots", headers=_auth(t2))
        assert [b["name"] for b in r1.json()] == ["HankBot"]
        assert [b["name"] for b in r2.json()] == ["IvyBot"]

    def test_bot_via_api_key(self, e2e_env):
        c = e2e_env["client"]
        token = _register(c, "jack", "jack@test.com")
        key = _create_key(c, token, "agent")["key"]

        # Register bot via API key
        res = c.post("/api/bots", json={"name": "AgentBot"}, headers=_apikey_header(key))
        assert res.status_code == 200
        assert res.json()["name"] == "AgentBot"

    def test_bot_details_forbidden_for_other_user(self, e2e_env):
        c = e2e_env["client"]
        t1 = _register(c, "kate", "kate@test.com")
        t2 = _register(c, "luna", "luna@test.com")

        bot = _create_bot(c, t1, "KateBot")
        res = c.get(f"/api/bots/{bot['id']}", headers=_auth(t2))
        assert res.status_code == 403


class TestQueueWorkflow:
    """Queue join, status, and leave."""

    def test_join_and_check_status(self, e2e_env):
        c = e2e_env["client"]
        token = _register(c, "maya", "maya@test.com")
        bot = _create_bot(c, token, "MayaBot")

        q = _join_queue(c, token, bot["id"])
        assert q["status"] == "waiting"
        assert q["position"] == 1
        assert q["bot_name"] == "MayaBot"

        # Check status
        res = c.get(f"/api/queue/status?bot_id={bot['id']}", headers=_auth(token))
        assert res.status_code == 200
        assert res.json()["status"] == "waiting"

    def test_double_queue_rejected(self, e2e_env):
        c = e2e_env["client"]
        token = _register(c, "nora", "nora@test.com")
        bot = _create_bot(c, token, "NoraBot")

        _join_queue(c, token, bot["id"])
        res = c.post("/api/queue/join", json={"bot_id": bot["id"]}, headers=_auth(token))
        assert res.status_code == 400

    def test_leave_queue(self, e2e_env):
        c = e2e_env["client"]
        token = _register(c, "omar", "omar@test.com")
        bot = _create_bot(c, token, "OmarBot")

        _join_queue(c, token, bot["id"])

        res = c.delete(f"/api/queue/leave?bot_id={bot['id']}", headers=_auth(token))
        assert res.status_code == 200

        # No longer queued
        res = c.get(f"/api/queue/status?bot_id={bot['id']}", headers=_auth(token))
        assert res.status_code == 404

    def test_queue_position_ordering(self, e2e_env):
        c = e2e_env["client"]
        t1 = _register(c, "pia", "pia@test.com")
        t2 = _register(c, "quinn", "quinn@test.com")
        t3 = _register(c, "ren", "ren@test.com")

        b1 = _create_bot(c, t1, "PiaBot")
        b2 = _create_bot(c, t2, "QuinnBot")
        b3 = _create_bot(c, t3, "RenBot")

        _join_queue(c, t1, b1["id"])
        _join_queue(c, t2, b2["id"])
        _join_queue(c, t3, b3["id"])

        # Check positions
        s1 = c.get(f"/api/queue/status?bot_id={b1['id']}", headers=_auth(t1)).json()
        s2 = c.get(f"/api/queue/status?bot_id={b2['id']}", headers=_auth(t2)).json()
        s3 = c.get(f"/api/queue/status?bot_id={b3['id']}", headers=_auth(t3)).json()

        assert s1["position"] == 1
        assert s2["position"] == 2
        assert s3["position"] == 3

    def test_cannot_queue_other_users_bot(self, e2e_env):
        c = e2e_env["client"]
        t1 = _register(c, "sara", "sara@test.com")
        t2 = _register(c, "tina", "tina@test.com")

        bot = _create_bot(c, t1, "SaraBot")
        res = c.post("/api/queue/join", json={"bot_id": bot["id"]}, headers=_auth(t2))
        assert res.status_code == 403


class TestMatchmakingE2E:
    """Queue → matchmaker → match → results → ELO."""

    def test_matchmaker_pairs_queued_bots(self, e2e_env):
        """Two bots queue → matchmaker creates match → results reported → ELO updated."""
        c = e2e_env["client"]
        db_factory = e2e_env["session_factory"]

        # Register two users with bots
        t1 = _register(c, "user_a", "a@test.com")
        t2 = _register(c, "user_b", "b@test.com")
        b1 = _create_bot(c, t1, "AlphaBot")
        b2 = _create_bot(c, t2, "BetaBot")

        # Queue both bots
        _join_queue(c, t1, b1["id"])
        _join_queue(c, t2, b2["id"])

        # Run matchmaker poll
        matchmaker = MatchMaker(db_session_factory=db_factory)
        match_id = matchmaker.poll_queue()
        assert match_id is not None

        # Verify match created in DB
        db = db_factory()
        try:
            match = db.query(MatchDB).filter(MatchDB.id == match_id).first()
            assert match is not None
            assert match.map_name == "q3dm17"

            participants = (
                db.query(MatchParticipantDB)
                .filter(MatchParticipantDB.match_id == match_id)
                .all()
            )
            assert len(participants) == 2
            bot_ids = {p.bot_id for p in participants}
            assert bot_ids == {b1["id"], b2["id"]}

            # Queue entries should be "matched"
            for p in participants:
                entry = (
                    db.query(QueueEntryDB)
                    .filter(QueueEntryDB.bot_id == p.bot_id)
                    .first()
                )
                assert entry.status == "matched"
        finally:
            db.close()

    def test_match_report_and_finalize(self, e2e_env):
        """Full lifecycle: match → report results → finalize → ELO updated."""
        c = e2e_env["client"]
        db_factory = e2e_env["session_factory"]

        # Setup: two users, two bots, both queued
        t1 = _register(c, "player1", "p1@test.com")
        t2 = _register(c, "player2", "p2@test.com")
        b1 = _create_bot(c, t1, "Warrior")
        b2 = _create_bot(c, t2, "Mage")

        _join_queue(c, t1, b1["id"])
        _join_queue(c, t2, b2["id"])

        # Matchmaker creates match
        matchmaker = MatchMaker(db_session_factory=db_factory)
        match_id = matchmaker.poll_queue()
        assert match_id is not None

        # Report results (Warrior wins: 10 kills, 3 deaths)
        r1 = _internal_report(c, match_id, b1["id"], "Warrior", kills=10, deaths=3)
        assert r1.status_code == 200

        # Report results (Mage loses: 3 kills, 10 deaths)
        r2 = _internal_report(c, match_id, b2["id"], "Mage", kills=3, deaths=10)
        assert r2.status_code == 200

        # Finalize match (ELO calculation)
        matchmaker.finalize_match(match_id)

        # Verify ELO changes
        db = db_factory()
        try:
            warrior = db.query(BotDB).filter(BotDB.id == b1["id"]).first()
            mage = db.query(BotDB).filter(BotDB.id == b2["id"]).first()

            # Winner ELO goes up, loser goes down
            assert warrior.elo > 1000.0
            assert mage.elo < 1000.0

            # ELO is conserved (zero-sum)
            total_elo = warrior.elo + mage.elo
            assert abs(total_elo - 2000.0) < 0.01

            # Stats updated
            assert warrior.kills == 10
            assert warrior.deaths == 3
            assert warrior.wins == 1
            assert warrior.losses == 0

            assert mage.kills == 3
            assert mage.deaths == 10
            assert mage.wins == 0
            assert mage.losses == 1

            # Match finalized
            match = db.query(MatchDB).filter(MatchDB.id == match_id).first()
            assert match.ended_at is not None
            assert match.winner == "Warrior"
        finally:
            db.close()

    def test_leaderboard_after_match(self, e2e_env):
        """Leaderboard reflects ELO after match finalization."""
        c = e2e_env["client"]
        db_factory = e2e_env["session_factory"]

        # Setup and run a complete match
        t1 = _register(c, "lead_a", "la@test.com")
        t2 = _register(c, "lead_b", "lb@test.com")
        b1 = _create_bot(c, t1, "Champion")
        b2 = _create_bot(c, t2, "Challenger")

        _join_queue(c, t1, b1["id"])
        _join_queue(c, t2, b2["id"])

        matchmaker = MatchMaker(db_session_factory=db_factory)
        match_id = matchmaker.poll_queue()
        _internal_report(c, match_id, b1["id"], "Champion", kills=15, deaths=2)
        _internal_report(c, match_id, b2["id"], "Challenger", kills=2, deaths=15)
        matchmaker.finalize_match(match_id)

        # Leaderboard shows correct order
        res = c.get("/api/leaderboard", headers=_auth(t1))
        assert res.status_code == 200
        lb = res.json()
        assert len(lb) == 2
        assert lb[0]["name"] == "Champion"  # Higher ELO = first
        assert lb[1]["name"] == "Challenger"
        assert lb[0]["elo"] > lb[1]["elo"]

    def test_match_detail_endpoint(self, e2e_env):
        """GET /api/matches/{id} returns participant details."""
        c = e2e_env["client"]
        db_factory = e2e_env["session_factory"]

        t1 = _register(c, "det_a", "da@test.com")
        t2 = _register(c, "det_b", "db@test.com")
        b1 = _create_bot(c, t1, "DetailBot1")
        b2 = _create_bot(c, t2, "DetailBot2")

        _join_queue(c, t1, b1["id"])
        _join_queue(c, t2, b2["id"])

        matchmaker = MatchMaker(db_session_factory=db_factory)
        match_id = matchmaker.poll_queue()
        _internal_report(c, match_id, b1["id"], "DetailBot1", kills=8, deaths=5)
        _internal_report(c, match_id, b2["id"], "DetailBot2", kills=5, deaths=8)
        matchmaker.finalize_match(match_id)

        # Get match details
        res = c.get(f"/api/matches/{match_id}")
        assert res.status_code == 200
        detail = res.json()
        assert detail["map_name"] == "q3dm17"
        assert detail["winner"] == "DetailBot1"
        assert len(detail["participants"]) == 2

        # Verify participant data
        p1 = next(p for p in detail["participants"] if p["bot_name"] == "DetailBot1")
        p2 = next(p for p in detail["participants"] if p["bot_name"] == "DetailBot2")
        assert p1["kills"] == 8
        assert p1["deaths"] == 5
        assert p1["elo_change"] > 0  # Winner gained ELO
        assert p2["elo_change"] < 0  # Loser lost ELO

    def test_match_history_endpoint(self, e2e_env):
        """GET /api/matches returns recent matches."""
        c = e2e_env["client"]
        db_factory = e2e_env["session_factory"]

        t1 = _register(c, "hist_a", "ha@test.com")
        t2 = _register(c, "hist_b", "hb@test.com")
        b1 = _create_bot(c, t1, "HistBot1")
        b2 = _create_bot(c, t2, "HistBot2")

        _join_queue(c, t1, b1["id"])
        _join_queue(c, t2, b2["id"])

        matchmaker = MatchMaker(db_session_factory=db_factory)
        match_id = matchmaker.poll_queue()
        _internal_report(c, match_id, b1["id"], "HistBot1", kills=6, deaths=4)
        _internal_report(c, match_id, b2["id"], "HistBot2", kills=4, deaths=6)
        matchmaker.finalize_match(match_id)

        res = c.get("/api/matches", headers=_auth(t1))
        assert res.status_code == 200
        matches = res.json()
        assert len(matches) >= 1
        assert matches[0]["winner"] == "HistBot1"


class TestMultiMatchELO:
    """Multiple matches verify ELO accumulation."""

    def test_repeated_matches_accumulate_stats(self, e2e_env):
        """Two matches between same bots — stats accumulate."""
        c = e2e_env["client"]
        db_factory = e2e_env["session_factory"]

        t1 = _register(c, "multi_a", "ma@test.com")
        t2 = _register(c, "multi_b", "mb@test.com")
        b1 = _create_bot(c, t1, "Repeater1")
        b2 = _create_bot(c, t2, "Repeater2")

        matchmaker = MatchMaker(db_session_factory=db_factory)

        # Match 1: b1 wins
        _join_queue(c, t1, b1["id"])
        _join_queue(c, t2, b2["id"])
        m1 = matchmaker.poll_queue()
        _internal_report(c, m1, b1["id"], "Repeater1", kills=10, deaths=5)
        _internal_report(c, m1, b2["id"], "Repeater2", kills=5, deaths=10)
        matchmaker.finalize_match(m1)

        db = db_factory()
        try:
            bot1_after_m1 = db.query(BotDB).filter(BotDB.id == b1["id"]).first()
            elo_after_m1 = bot1_after_m1.elo
            assert elo_after_m1 > 1000.0
        finally:
            db.close()

        # Match 2: b1 wins again (should gain less ELO since already ahead)
        _join_queue(c, t1, b1["id"])
        _join_queue(c, t2, b2["id"])
        m2 = matchmaker.poll_queue()
        _internal_report(c, m2, b1["id"], "Repeater1", kills=8, deaths=3)
        _internal_report(c, m2, b2["id"], "Repeater2", kills=3, deaths=8)
        matchmaker.finalize_match(m2)

        db = db_factory()
        try:
            bot1_final = db.query(BotDB).filter(BotDB.id == b1["id"]).first()
            bot2_final = db.query(BotDB).filter(BotDB.id == b2["id"]).first()

            # Further ELO gain but smaller (since already favoured)
            assert bot1_final.elo > elo_after_m1

            # Cumulative stats
            assert bot1_final.kills == 18  # 10 + 8
            assert bot1_final.deaths == 8  # 5 + 3
            assert bot1_final.wins == 2
            assert bot1_final.losses == 0

            assert bot2_final.wins == 0
            assert bot2_final.losses == 2
        finally:
            db.close()


class TestFourPlayerFFA:
    """4-player FFA match E2E."""

    def test_four_player_match(self, e2e_env):
        c = e2e_env["client"]
        db_factory = e2e_env["session_factory"]

        tokens = []
        bots = []
        for i in range(4):
            t = _register(c, f"ffa_p{i}", f"ffa{i}@test.com")
            b = _create_bot(c, t, f"FFABot{i}")
            tokens.append(t)
            bots.append(b)

        # Queue all 4
        for t, b in zip(tokens, bots):
            _join_queue(c, t, b["id"])

        # Matchmaker picks up to MAX_PLAYERS (4)
        matchmaker = MatchMaker(db_session_factory=db_factory)
        match_id = matchmaker.poll_queue()
        assert match_id is not None

        # Report varied results
        scores = [(15, 3), (10, 5), (5, 10), (3, 15)]
        for (kills, deaths), b in zip(scores, bots):
            _internal_report(c, match_id, b["id"], b["name"], kills=kills, deaths=deaths)

        matchmaker.finalize_match(match_id)

        # Verify: best performer wins, ELO reflects rank
        db = db_factory()
        try:
            match = db.query(MatchDB).filter(MatchDB.id == match_id).first()
            assert match.winner == "FFABot0"  # 15 kills, 3 deaths

            elos = []
            for b in bots:
                bot = db.query(BotDB).filter(BotDB.id == b["id"]).first()
                elos.append(bot.elo)

            # ELOs should be in descending order
            assert elos[0] > elos[1] > elos[2] > elos[3]

            # Total ELO conserved
            total = sum(elos)
            assert abs(total - 4000.0) < 0.1
        finally:
            db.close()


class TestInternalMatchReport:
    """Internal match reporting edge cases."""

    def test_invalid_secret_rejected(self, e2e_env):
        c = e2e_env["client"]
        res = c.post("/api/internal/match/report", json={
            "match_id": 999,
            "bot_id": 1,
            "bot_name": "Fake",
            "kills": 0,
            "deaths": 0,
            "duration_seconds": 0,
        }, headers={"X-Internal-Secret": "wrong-secret"})
        assert res.status_code == 403

    def test_nonexistent_participant_rejected(self, e2e_env):
        c = e2e_env["client"]
        res = _internal_report(c, match_id=99999, bot_id=99999, bot_name="Ghost", kills=0, deaths=0)
        assert res.status_code == 404


class TestHealthAndStatus:
    """Basic health and status endpoints."""

    def test_health(self, e2e_env):
        c = e2e_env["client"]
        res = c.get("/api/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    def test_unauthenticated_endpoints_reject(self, e2e_env):
        c = e2e_env["client"]

        # These require auth
        assert c.get("/api/leaderboard").status_code == 403
        assert c.get("/api/matches").status_code == 403
        assert c.get("/api/auth/me").status_code == 403
        assert c.get("/api/bots").status_code == 401
        assert c.get("/api/keys").status_code == 403

    def test_nonexistent_match_404(self, e2e_env):
        c = e2e_env["client"]
        res = c.get("/api/matches/99999")
        assert res.status_code == 404
