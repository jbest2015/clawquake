"""
TelemetryHub — Per-bot pub/sub with bounded queues for WebSocket fan-out.

Subscribers receive telemetry frames at up to 20Hz. Slow consumers get
oldest frames dropped (bounded queue). A dropped_frames counter is
injected so subscribers know they're behind.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

logger = logging.getLogger("clawquake.telemetry_hub")

# Valid bot action prefixes — anything else is rejected
VALID_ACTIONS = frozenset({
    "move_forward", "move_backward", "move_left", "move_right",
    "jump", "crouch", "attack", "use_weapon",
    "aim_at", "look_at", "strafe_left", "strafe_right",
    "idle", "stop",
})

MAX_QUEUE_SIZE = 10


_SHELL_META = re.compile(r'[;&|`$\n\r\\]')


def validate_action(action_str: str) -> bool:
    """Check if an action string is in the whitelist.

    Actions are either a bare command (e.g. 'jump') or a command with
    space-separated params (e.g. 'aim_at 100 200 50').
    Rejects any string containing shell metacharacters.
    """
    if not action_str or not isinstance(action_str, str) or not action_str.strip():
        return False
    stripped = action_str.strip()
    # Reject shell metacharacters anywhere in the string
    if _SHELL_META.search(stripped):
        return False
    cmd = stripped.split()[0]
    return cmd in VALID_ACTIONS


class TelemetryHub:
    """Per-bot pub/sub with bounded queues for WebSocket fan-out."""

    def __init__(self):
        self._subscribers: dict[int, set[asyncio.Queue]] = {}
        self._dropped: dict[int, int] = {}  # per-subscriber dropped count
        self._lock = asyncio.Lock()

    async def publish(self, bot_id: int, frame: dict[str, Any]) -> None:
        """Publish a telemetry frame to all subscribers for a bot.

        If a subscriber's queue is full, the oldest frame is dropped
        and the dropped_frames counter is incremented.
        """
        async with self._lock:
            queues = self._subscribers.get(bot_id)
            if not queues:
                return
            targets = list(queues)

        for q in targets:
            q_id = id(q)
            try:
                q.put_nowait(frame)
            except asyncio.QueueFull:
                # Drop oldest, put new
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(frame)
                except asyncio.QueueFull:
                    pass
                self._dropped[q_id] = self._dropped.get(q_id, 0) + 1
                logger.debug(
                    "Dropped frame for bot %d subscriber (total dropped: %d)",
                    bot_id, self._dropped[q_id],
                )

    def get_dropped_frames(self, queue: asyncio.Queue) -> int:
        """Get the number of dropped frames for a subscriber's queue."""
        return self._dropped.get(id(queue), 0)

    async def subscribe(self, bot_id: int) -> asyncio.Queue:
        """Subscribe to telemetry for a bot. Returns a bounded queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        async with self._lock:
            if bot_id not in self._subscribers:
                self._subscribers[bot_id] = set()
            self._subscribers[bot_id].add(q)
        logger.info("Subscriber added for bot %d (total: %d)",
                     bot_id, len(self._subscribers[bot_id]))
        return q

    async def unsubscribe(self, bot_id: int, queue: asyncio.Queue) -> None:
        """Remove a subscriber's queue."""
        async with self._lock:
            queues = self._subscribers.get(bot_id)
            if queues:
                queues.discard(queue)
                if not queues:
                    del self._subscribers[bot_id]
        self._dropped.pop(id(queue), None)
        logger.info("Subscriber removed for bot %d", bot_id)

    def subscriber_count(self, bot_id: int) -> int:
        """Number of active subscribers for a bot."""
        return len(self._subscribers.get(bot_id, set()))
