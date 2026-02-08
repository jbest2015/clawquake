"""
WebSocket hub for broadcasting live orchestrator events.
"""

from __future__ import annotations

from asyncio import Lock
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket


class WebSocketHub:
    """Tracks active clients and broadcasts JSON events."""

    def __init__(self):
        self._connections: set[WebSocket] = set()
        self._lock = Lock()

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, event_type: str, data: Any):
        message = {
            "event_type": event_type,
            "data": data,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        async with self._lock:
            targets = list(self._connections)

        stale: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)

        if stale:
            async with self._lock:
                for ws in stale:
                    self._connections.discard(ws)
