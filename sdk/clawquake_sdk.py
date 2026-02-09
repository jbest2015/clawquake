"""
ClawQuake SDK client.

Provides a thin Python wrapper around ClawQuake HTTP and WebSocket APIs.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from contextlib import suppress
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
import websockets


class ClawQuakeClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        jwt_token: str | None = None,
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.jwt_token = jwt_token
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        elif self.jwt_token:
            headers["Authorization"] = f"Bearer {self.jwt_token}"
        return headers

    def _request(self, method: str, path: str, **kwargs) -> Any:
        headers = kwargs.pop("headers", {})
        merged_headers = {**self._headers(), **headers}
        response = self._http.request(method, path, headers=merged_headers, **kwargs)
        response.raise_for_status()
        if response.content:
            return response.json()
        return None

    # ── Auth ────────────────────────────────────────────────

    def register(self, username: str, email: str, password: str) -> dict:
        data = self._request(
            "POST",
            "/api/auth/register",
            json={"username": username, "email": email, "password": password},
        )
        token = data.get("access_token")
        if token:
            self.jwt_token = token
        return data

    def login(self, username: str, password: str) -> dict:
        data = self._request(
            "POST",
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        token = data.get("access_token")
        if token:
            self.jwt_token = token
        return data

    # ── Keys ────────────────────────────────────────────────

    def create_key(self, name: str, expires_in_days: int | None = None) -> dict:
        payload: dict[str, Any] = {"name": name}
        if expires_in_days is not None:
            payload["expires_in_days"] = expires_in_days
        return self._request("POST", "/api/keys", json=payload)

    def list_keys(self) -> list[dict]:
        return self._request("GET", "/api/keys")

    def delete_key(self, key_id: int) -> bool:
        data = self._request("DELETE", f"/api/keys/{key_id}")
        return bool(data.get("deleted"))

    def rotate_key(self, key_id: int) -> dict:
        return self._request("POST", f"/api/keys/{key_id}/rotate")

    # ── Bots ────────────────────────────────────────────────

    def register_bot(self, name: str) -> dict:
        return self._request("POST", "/api/bots", json={"name": name})

    def list_bots(self) -> list[dict]:
        return self._request("GET", "/api/bots")

    def get_bot(self, bot_id: int) -> dict:
        return self._request("GET", f"/api/bots/{bot_id}")

    # ── Queue ───────────────────────────────────────────────

    def join_queue(self, bot_id: int) -> dict:
        return self._request("POST", "/api/queue/join", json={"bot_id": bot_id})

    def check_status(self, bot_id: int) -> dict:
        return self._request("GET", "/api/queue/status", params={"bot_id": bot_id})

    def leave_queue(self, bot_id: int) -> bool:
        data = self._request("DELETE", "/api/queue/leave", params={"bot_id": bot_id})
        return bool(data.get("left"))

    # ── Matches ──────────────────────────────────────────────

    def get_match(self, match_id: int) -> dict:
        return self._request("GET", f"/api/matches/{match_id}")

    # ── Status ───────────────────────────────────────────────

    def health(self) -> dict:
        return self._request("GET", "/api/health")

    def status(self) -> dict:
        return self._request("GET", "/api/status")

    # ── Events ───────────────────────────────────────────────

    def _events_url(self) -> str:
        parsed = urlparse(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        host = parsed.netloc
        return f"{scheme}://{host}/ws/events"

    @asynccontextmanager
    async def connect_events(self, on_event: Callable[[dict], Any]):
        """
        Connect to the live event stream and invoke `on_event` for each message.

        Usage:
            async with client.connect_events(handler):
                await asyncio.sleep(30)
        """
        ws = await websockets.connect(self._events_url())
        stop = asyncio.Event()

        async def _listener():
            while not stop.is_set():
                raw = await ws.recv()
                message = json.loads(raw)
                result = on_event(message)
                if asyncio.iscoroutine(result):
                    await result

        task = asyncio.create_task(_listener())
        try:
            yield ws
        finally:
            stop.set()
            task.cancel()
            with suppress(Exception):
                await task
            await ws.close()
