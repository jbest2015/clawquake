"""
Tests for websocket event hub.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))

from websocket_hub import WebSocketHub


class DummyWebSocket:
    def __init__(self):
        self.accepted = False
        self.messages: list[dict] = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.messages.append(payload)


@pytest.mark.asyncio
async def test_connect():
    hub = WebSocketHub()
    ws = DummyWebSocket()
    await hub.connect(ws)
    assert ws.accepted is True
    assert hub.connection_count == 1


@pytest.mark.asyncio
async def test_broadcast():
    hub = WebSocketHub()
    ws1 = DummyWebSocket()
    ws2 = DummyWebSocket()
    await hub.connect(ws1)
    await hub.connect(ws2)

    await hub.broadcast("queue_update", {"waiting_entries": 2})

    assert len(ws1.messages) == 1
    assert len(ws2.messages) == 1
    assert ws1.messages[0]["event_type"] == "queue_update"
    assert ws1.messages[0]["data"]["waiting_entries"] == 2


@pytest.mark.asyncio
async def test_disconnect():
    hub = WebSocketHub()
    ws = DummyWebSocket()
    await hub.connect(ws)
    assert hub.connection_count == 1
    await hub.disconnect(ws)
    assert hub.connection_count == 0
