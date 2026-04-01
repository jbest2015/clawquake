"""
Tests for the dashboard bot telemetry WebSocket endpoint (5Hz rate-limited).

Tests the /ws/bot-telemetry/{bot_id} endpoint that dashboard spectators
use to view live bot state when clicking leaderboard rows.
"""

import asyncio
import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only")
os.environ.setdefault("RCON_PASSWORD", "test-rcon-password")
os.environ.setdefault("INTERNAL_SECRET", "test-internal-secret")

from telemetry_hub import TelemetryHub


@pytest.fixture
def hub():
    return TelemetryHub()


class TestDashboardTelemetryRateLimiting:
    """Verify the 5Hz rate-limiting logic works correctly."""

    @pytest.mark.asyncio
    async def test_subscriber_receives_published_frames(self, hub):
        """Basic pub/sub: subscriber gets frames published to the hub."""
        q = await hub.subscribe(1)
        await hub.publish(1, {"type": "telemetry", "tick": 1, "state": {"health": 100}})
        frame = q.get_nowait()
        assert frame["tick"] == 1

    @pytest.mark.asyncio
    async def test_rate_limit_drains_to_latest(self, hub):
        """When multiple frames arrive between intervals, only latest is kept."""
        q = await hub.subscribe(1)

        # Publish 5 frames rapidly
        for i in range(5):
            await hub.publish(1, {"type": "telemetry", "tick": i, "state": {"health": 100 - i}})

        # Drain like the dashboard endpoint does — keep only latest
        latest = None
        while not q.empty():
            try:
                latest = q.get_nowait()
            except asyncio.QueueEmpty:
                break

        assert latest is not None
        assert latest["tick"] == 4  # last frame wins

    @pytest.mark.asyncio
    async def test_empty_queue_produces_no_frame(self, hub):
        """If no frames arrive in an interval, nothing is sent."""
        q = await hub.subscribe(1)
        assert q.empty()
        # No frames published — drain should yield None
        latest = None
        while not q.empty():
            try:
                latest = q.get_nowait()
            except asyncio.QueueEmpty:
                break
        assert latest is None

    @pytest.mark.asyncio
    async def test_different_bots_isolated(self, hub):
        """Dashboard subscribing to bot 1 does not receive bot 2 frames."""
        q1 = await hub.subscribe(1)
        q2 = await hub.subscribe(2)
        await hub.publish(1, {"type": "telemetry", "tick": 1, "bot_id": 1})
        await hub.publish(2, {"type": "telemetry", "tick": 1, "bot_id": 2})
        assert q1.get_nowait()["bot_id"] == 1
        assert q2.get_nowait()["bot_id"] == 2
        assert q1.empty()
        assert q2.empty()

    @pytest.mark.asyncio
    async def test_event_frames_forwarded(self, hub):
        """Kill events and other event types are forwarded to subscribers."""
        q = await hub.subscribe(1)
        await hub.publish(1, {
            "type": "event",
            "event_type": "kill",
            "data": {"killer": "BotA", "victim": "BotB", "weapon": "railgun"},
        })
        frame = q.get_nowait()
        assert frame["type"] == "event"
        assert frame["data"]["killer"] == "BotA"

    @pytest.mark.asyncio
    async def test_disconnect_event_forwarded(self, hub):
        """Disconnect events are forwarded when a bot runner disconnects."""
        q = await hub.subscribe(1)
        await hub.publish(1, {"type": "disconnected", "bot_id": 1})
        frame = q.get_nowait()
        assert frame["type"] == "disconnected"

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self, hub):
        """After unsubscribe, no more frames are delivered."""
        q = await hub.subscribe(1)
        await hub.unsubscribe(1, q)
        await hub.publish(1, {"type": "telemetry", "tick": 99})
        assert q.empty()


class TestDashboardTelemetryConstants:
    """Verify rate-limiting constants are properly set."""

    def test_dashboard_hz_is_5(self):
        # Import from main to verify the constant
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))
        import importlib
        import main
        importlib.reload(main)
        assert main.DASHBOARD_TELEMETRY_HZ == 5
        assert abs(main.DASHBOARD_TELEMETRY_INTERVAL - 0.2) < 0.001
