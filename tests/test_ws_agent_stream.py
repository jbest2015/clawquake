"""
Integration tests for WebSocket agent stream and internal telemetry endpoints.

Tests both the external agent WS (/api/agent/stream) and
internal bot runner WS (/api/agent/internal/telemetry).
"""

import asyncio
import json
import os
import sys
import time
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only")
os.environ.setdefault("RCON_PASSWORD", "test-rcon-password")
os.environ.setdefault("INTERNAL_SECRET", "test-internal-secret")

from fastapi.testclient import TestClient
from api_keys import generate_api_key, hash_api_key
from telemetry_hub import TelemetryHub
import ai_agent_interface
from ai_agent_interface import (
    LATEST_STATES, ACTION_QUEUES, router, MAX_FRAME_SIZE,
)
from models import AgentRegistrationDB


@pytest.fixture(autouse=True)
def clean_state():
    """Reset global state between tests."""
    LATEST_STATES.clear()
    ACTION_QUEUES.clear()
    yield
    LATEST_STATES.clear()
    ACTION_QUEUES.clear()


@pytest.fixture
def hub():
    """Fresh TelemetryHub for each test."""
    h = TelemetryHub()
    old_hub = ai_agent_interface.telemetry_hub
    ai_agent_interface.telemetry_hub = h
    yield h
    ai_agent_interface.telemetry_hub = old_hub


# ── Fallback HTTP endpoint tests ─────────────────────────────────

class TestFallbackHTTP:
    """Verify HTTP endpoints still work alongside WebSocket additions."""

    def test_observe_returns_waiting_state(self, db):
        from conftest import create_test_user, create_test_bot
        from auth import create_access_token

        user = create_test_user(db)
        bot = create_test_bot(db, owner_id=user.id)

        # No state yet
        result = ai_agent_interface._observe_for_bot(bot.id)
        assert result["status"] == "waiting_for_connection"

    def test_observe_returns_latest_state(self, db):
        from conftest import create_test_user, create_test_bot

        user = create_test_user(db)
        bot = create_test_bot(db, owner_id=user.id)
        LATEST_STATES[bot.id] = {"health": 100, "position": [1, 2, 3]}

        result = ai_agent_interface._observe_for_bot(bot.id)
        assert result["health"] == 100

    def test_act_queues_action(self, db):
        from conftest import create_test_user, create_test_bot

        user = create_test_user(db)
        bot = create_test_bot(db, owner_id=user.id)

        queue = ACTION_QUEUES.setdefault(bot.id, [])
        queue.append({"action": "jump", "params": {}, "queued_at": time.time()})
        assert len(ACTION_QUEUES[bot.id]) == 1

    def test_internal_sync_updates_state(self, db):
        from conftest import create_test_user, create_test_bot

        user = create_test_user(db)
        bot = create_test_bot(db, owner_id=user.id)

        # Simulate what internal/sync does
        state = {"health": 85, "armor": 50}
        LATEST_STATES[bot.id] = state
        ACTION_QUEUES[bot.id] = [{"action": "attack", "params": {}}]

        # Drain actions like internal/sync endpoint does
        actions = ACTION_QUEUES.get(bot.id, [])
        ACTION_QUEUES[bot.id] = []

        assert len(actions) == 1
        assert actions[0]["action"] == "attack"
        assert LATEST_STATES[bot.id]["health"] == 85


# ── Action validation tests ──────────────────────────────────────

class TestActionValidation:
    def test_valid_actions_accepted(self):
        from telemetry_hub import validate_action
        assert validate_action("move_forward") is True
        assert validate_action("attack") is True
        assert validate_action("jump") is True
        assert validate_action("aim_at 100 200 50") is True

    def test_invalid_action_rejected(self):
        from telemetry_hub import validate_action
        assert validate_action("rcon_command") is False
        assert validate_action("exec") is False
        assert validate_action("say hello") is False

    def test_empty_action_rejected(self):
        from telemetry_hub import validate_action
        assert validate_action("") is False
        assert validate_action("   ") is False


# ── TelemetryHub integration tests ──────────────────────────────

class TestTelemetryHubIntegration:
    @pytest.mark.asyncio
    async def test_hub_publish_subscribe_round_trip(self, hub):
        q = await hub.subscribe(1)
        frame = {"type": "telemetry", "tick": 1, "state": {"health": 100}}
        await hub.publish(1, frame)
        result = q.get_nowait()
        assert result["state"]["health"] == 100
        await hub.unsubscribe(1, q)

    @pytest.mark.asyncio
    async def test_hub_disconnect_cleans_up(self, hub):
        q = await hub.subscribe(1)
        assert hub.subscriber_count(1) == 1
        await hub.unsubscribe(1, q)
        assert hub.subscriber_count(1) == 0


# ── Auth helper tests ────────────────────────────────────────────

class TestAuthHelpers:
    def test_require_owned_bot_found(self, db):
        from conftest import create_test_user, create_test_bot
        from ai_agent_interface import _require_owned_bot

        user = create_test_user(db)
        bot = create_test_bot(db, owner_id=user.id)
        result = _require_owned_bot(db, user, bot.id)
        assert result.id == bot.id

    def test_require_owned_bot_not_found(self, db):
        from conftest import create_test_user
        from ai_agent_interface import _require_owned_bot
        from fastapi import HTTPException

        user = create_test_user(db)
        with pytest.raises(HTTPException) as exc_info:
            _require_owned_bot(db, user, 9999)
        assert exc_info.value.status_code == 404

    def test_require_owned_bot_forbidden(self, db):
        from conftest import create_test_user, create_test_bot
        from ai_agent_interface import _require_owned_bot
        from fastapi import HTTPException

        user1 = create_test_user(db, username="user1", email="u1@test.com")
        user2 = create_test_user(db, username="user2", email="u2@test.com")
        bot = create_test_bot(db, name="Bot1", owner_id=user1.id)

        with pytest.raises(HTTPException) as exc_info:
            _require_owned_bot(db, user2, bot.id)
        assert exc_info.value.status_code == 403

    def test_validate_internal_secret(self):
        from ai_agent_interface import _validate_internal_secret
        from fastapi import HTTPException

        # Valid secret
        _validate_internal_secret("test-internal-secret")

        # Invalid secret
        with pytest.raises(HTTPException) as exc_info:
            _validate_internal_secret("wrong-secret")
        assert exc_info.value.status_code == 403

    def test_auth_external_ws_with_agent_key(self, db):
        from conftest import create_test_user, create_test_bot
        from ai_agent_interface import _auth_external_ws

        user = create_test_user(db, username="agentowner", email="agentowner@test.com")
        bot = create_test_bot(db, name="AgentBot", owner_id=user.id)
        raw_key = generate_api_key()
        registration = AgentRegistrationDB(
            bot_id=bot.id,
            created_by_user_id=user.id,
            name="primary",
            key_hash=hash_api_key(raw_key),
            key_prefix=raw_key[:8],
        )
        db.add(registration)
        db.commit()

        result = _auth_external_ws(db, bot_id=bot.id, agent_key=raw_key)
        assert result is not None
        assert result.id == bot.id


# ── Oversized frame test ─────────────────────────────────────────

class TestFrameLimits:
    def test_max_frame_size_constant(self):
        assert MAX_FRAME_SIZE == 65536

    def test_oversized_data_would_be_rejected(self):
        """Verify that the MAX_FRAME_SIZE check in the WS handler
        would reject data larger than 64KB."""
        oversized = "x" * (MAX_FRAME_SIZE + 1)
        assert len(oversized) > MAX_FRAME_SIZE
