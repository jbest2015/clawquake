"""
Tests for API key expiry enforcement in matchmaker bot launching.
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))
sys.path.insert(0, os.path.dirname(__file__))

from conftest import create_test_bot, create_test_user, queue_bot
from matchmaker import MatchMaker
from models import ApiKeyDB


class DummyProcessManager:
    def __init__(self):
        self.launch_calls: list[dict] = []
        self.cleaned: list[int] = []

    def launch_match(self, match_id, bots, server_url, duration):
        self.launch_calls.append(
            {
                "match_id": match_id,
                "bots": bots,
                "server_url": server_url,
                "duration": duration,
            }
        )

    async def wait_for_match(self, match_id):
        return {"all_finished": True, "match_id": match_id}

    def cleanup_match(self, match_id):
        self.cleaned.append(match_id)


def _add_key(db, user_id: int, active: bool, expires_at):
    db.add(
        ApiKeyDB(
            user_id=user_id,
            name="k",
            key_hash=f"h_{user_id}_{active}_{expires_at}",
            key_prefix="cq_demo",
            is_active=1 if active else 0,
            expires_at=expires_at,
        )
    )
    db.commit()


@pytest.mark.asyncio
async def test_skips_bots_with_expired_keys(db, db_factory, monkeypatch):
    expired_user = create_test_user(db, username="expired_u", email="expired@example.com")
    active_user = create_test_user(db, username="active_u", email="active@example.com")
    expired_bot = create_test_bot(db, name="ExpiredBot", owner_id=expired_user.id)
    active_bot = create_test_bot(db, name="ActiveBot", owner_id=active_user.id)

    _add_key(
        db,
        user_id=expired_user.id,
        active=True,
        expires_at=datetime.utcnow() - timedelta(days=1),
    )
    _add_key(
        db,
        user_id=active_user.id,
        active=True,
        expires_at=datetime.utcnow() + timedelta(days=2),
    )

    e1 = queue_bot(db, expired_bot.id, expired_user.id)
    e2 = queue_bot(db, active_bot.id, active_user.id)

    pm = DummyProcessManager()
    mm = MatchMaker(db_session_factory=db_factory, process_manager=pm)
    monkeypatch.setattr(mm, "_get_server_url", lambda: "ws://test-server:27960")
    monkeypatch.setattr(mm, "_get_bot_strategy", lambda _db, _bot_id: "strategies/default.py")
    monkeypatch.setattr(mm, "finalize_match", lambda _match_id: None)

    match_id = mm.create_match(db, [e1, e2])
    await mm._run_match_with_processes(match_id, [expired_bot.id, active_bot.id])

    assert len(pm.launch_calls) == 1
    launched = pm.launch_calls[0]["bots"]
    assert len(launched) == 1
    assert launched[0]["bot_id"] == active_bot.id


@pytest.mark.asyncio
async def test_no_launch_when_all_owners_invalid(db, db_factory, monkeypatch):
    user1 = create_test_user(db, username="u1", email="u1@example.com")
    user2 = create_test_user(db, username="u2", email="u2@example.com")
    bot1 = create_test_bot(db, name="BotOne", owner_id=user1.id)
    bot2 = create_test_bot(db, name="BotTwo", owner_id=user2.id)

    _add_key(
        db,
        user_id=user1.id,
        active=False,
        expires_at=datetime.utcnow() + timedelta(days=5),
    )
    _add_key(
        db,
        user_id=user2.id,
        active=True,
        expires_at=datetime.utcnow() - timedelta(hours=1),
    )

    e1 = queue_bot(db, bot1.id, user1.id)
    e2 = queue_bot(db, bot2.id, user2.id)

    pm = DummyProcessManager()
    mm = MatchMaker(db_session_factory=db_factory, process_manager=pm)
    monkeypatch.setattr(mm, "_get_server_url", lambda: "ws://test-server:27960")

    finalized = {"called": False}
    monkeypatch.setattr(
        mm,
        "finalize_match",
        lambda _match_id: finalized.__setitem__("called", True),
    )

    match_id = mm.create_match(db, [e1, e2])
    await mm._run_match_with_processes(match_id, [bot1.id, bot2.id])

    assert pm.launch_calls == []
    assert finalized["called"] is True
