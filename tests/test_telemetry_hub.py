"""
Tests for TelemetryHub — per-bot pub/sub with bounded queues.
"""

import asyncio
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))

from telemetry_hub import TelemetryHub, validate_action, VALID_ACTIONS, MAX_QUEUE_SIZE


# ── validate_action tests ────────────────────────────────────────

class TestValidateAction:
    def test_valid_bare_commands(self):
        for action in VALID_ACTIONS:
            assert validate_action(action) is True, f"{action} should be valid"

    def test_valid_action_with_params(self):
        assert validate_action("aim_at 100 200 50") is True
        assert validate_action("move_forward ") is True

    def test_invalid_action_rejected(self):
        assert validate_action("rcon_command") is False
        assert validate_action("exec") is False
        assert validate_action("drop_weapon") is False
        assert validate_action("say hello") is False

    def test_empty_action_rejected(self):
        assert validate_action("") is False
        assert validate_action("   ") is False

    def test_none_action_rejected(self):
        assert validate_action(None) is False

    def test_command_injection_blocked(self):
        assert validate_action("jump; rm -rf /") is False
        assert validate_action("attack && echo pwned") is False
        assert validate_action("jump ; rm") is False  # shell metacharacters rejected
        assert validate_action("jump") is True


# ── TelemetryHub tests ───────────────────────────────────────────

@pytest.fixture
def hub():
    return TelemetryHub()


class TestTelemetryHub:
    @pytest.mark.asyncio
    async def test_subscribe_creates_queue(self, hub):
        q = await hub.subscribe(1)
        assert isinstance(q, asyncio.Queue)
        assert q.maxsize == MAX_QUEUE_SIZE

    @pytest.mark.asyncio
    async def test_publish_delivers_to_subscriber(self, hub):
        q = await hub.subscribe(1)
        frame = {"type": "telemetry", "tick": 1}
        await hub.publish(1, frame)
        result = q.get_nowait()
        assert result == frame

    @pytest.mark.asyncio
    async def test_publish_fan_out_multiple_subscribers(self, hub):
        q1 = await hub.subscribe(1)
        q2 = await hub.subscribe(1)
        frame = {"type": "telemetry", "tick": 42}
        await hub.publish(1, frame)
        assert q1.get_nowait() == frame
        assert q2.get_nowait() == frame

    @pytest.mark.asyncio
    async def test_bounded_queue_drops_oldest(self, hub):
        q = await hub.subscribe(1)
        # Fill the queue
        for i in range(MAX_QUEUE_SIZE):
            await hub.publish(1, {"tick": i})
        # Queue is full, publish one more
        await hub.publish(1, {"tick": MAX_QUEUE_SIZE})
        # Oldest (tick=0) should be dropped, newest should be present
        first = q.get_nowait()
        assert first["tick"] == 1  # tick=0 was dropped

    @pytest.mark.asyncio
    async def test_dropped_frames_counter(self, hub):
        q = await hub.subscribe(1)
        # Fill queue
        for i in range(MAX_QUEUE_SIZE):
            await hub.publish(1, {"tick": i})
        assert hub.get_dropped_frames(q) == 0
        # Overflow by 3
        for i in range(3):
            await hub.publish(1, {"tick": MAX_QUEUE_SIZE + i})
        assert hub.get_dropped_frames(q) == 3

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_queue(self, hub):
        q = await hub.subscribe(1)
        await hub.unsubscribe(1, q)
        # Publishing should not deliver to unsubscribed queue
        await hub.publish(1, {"tick": 1})
        assert q.empty()

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_is_noop(self, hub):
        q = asyncio.Queue()
        # Should not raise
        await hub.unsubscribe(999, q)

    @pytest.mark.asyncio
    async def test_publish_to_no_subscribers(self, hub):
        # Should not raise
        await hub.publish(1, {"tick": 1})

    @pytest.mark.asyncio
    async def test_subscriber_count(self, hub):
        assert hub.subscriber_count(1) == 0
        q1 = await hub.subscribe(1)
        assert hub.subscriber_count(1) == 1
        q2 = await hub.subscribe(1)
        assert hub.subscriber_count(1) == 2
        await hub.unsubscribe(1, q1)
        assert hub.subscriber_count(1) == 1

    @pytest.mark.asyncio
    async def test_different_bots_isolated(self, hub):
        q1 = await hub.subscribe(1)
        q2 = await hub.subscribe(2)
        await hub.publish(1, {"bot": 1})
        await hub.publish(2, {"bot": 2})
        assert q1.get_nowait()["bot"] == 1
        assert q2.get_nowait()["bot"] == 2
        # Each queue should only have 1 item
        assert q1.empty()
        assert q2.empty()

    @pytest.mark.asyncio
    async def test_unsubscribe_cleans_dropped_counter(self, hub):
        q = await hub.subscribe(1)
        # Fill + overflow
        for i in range(MAX_QUEUE_SIZE + 5):
            await hub.publish(1, {"tick": i})
        assert hub.get_dropped_frames(q) > 0
        await hub.unsubscribe(1, q)
        # Counter should be cleaned up
        assert hub.get_dropped_frames(q) == 0
