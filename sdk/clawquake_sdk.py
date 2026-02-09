"""
ClawQuake SDK client.

Provides a thin Python wrapper around ClawQuake HTTP and WebSocket APIs.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
import websockets


@dataclass
class ClawQuakeError(Exception):
    message: str
    status_code: int | None = None

    def __str__(self) -> str:
        if self.status_code is None:
            return self.message
        return f"{self.status_code}: {self.message}"


class AuthenticationError(ClawQuakeError):
    pass


class ForbiddenError(ClawQuakeError):
    pass


class NotFoundError(ClawQuakeError):
    pass


class ConflictError(ClawQuakeError):
    pass


@dataclass
class RateLimitError(ClawQuakeError):
    retry_after: float | None = None


class ServerError(ClawQuakeError):
    pass


class ClawQuakeClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        jwt_token: str | None = None,
        timeout: float = 10.0,
        max_retries: int = 2,
        backoff_base: float = 0.25,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.jwt_token = jwt_token
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout)
        self.max_retries = max(0, max_retries)
        self.backoff_base = max(0.0, backoff_base)

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
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._http.request(method, path, headers=merged_headers, **kwargs)
                response.raise_for_status()
                if response.content:
                    return response.json()
                return None
            except httpx.HTTPStatusError as exc:
                response = exc.response
                status_code = response.status_code

                if status_code in (429, 503) and attempt <= self.max_retries:
                    delay = self._retry_delay(response, attempt)
                    if delay > 0:
                        self._sleep(delay)
                    continue

                raise self._map_http_error(exc) from exc
            except httpx.RequestError as exc:
                raise ServerError(str(exc), status_code=None) from exc

    def _sleep(self, seconds: float):
        import time
        time.sleep(seconds)

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after_header = response.headers.get("retry-after")
        header_delay: float | None = None
        if retry_after_header is not None:
            try:
                header_delay = max(0.0, float(retry_after_header))
            except ValueError:
                header_delay = None
        exp_delay = self.backoff_base * (2 ** (attempt - 1))
        if header_delay is None:
            return exp_delay
        return max(header_delay, exp_delay)

    def _error_detail(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict) and "detail" in payload:
                detail = payload["detail"]
                if isinstance(detail, str):
                    return detail
                return json.dumps(detail)
        except Exception:
            pass
        if response.text:
            return response.text
        return response.reason_phrase or "Request failed"

    def _map_http_error(self, exc: httpx.HTTPStatusError) -> ClawQuakeError:
        response = exc.response
        status_code = response.status_code
        detail = self._error_detail(response)
        if status_code == 401:
            return AuthenticationError(detail, status_code=status_code)
        if status_code == 403:
            return ForbiddenError(detail, status_code=status_code)
        if status_code == 404:
            return NotFoundError(detail, status_code=status_code)
        if status_code == 409:
            return ConflictError(detail, status_code=status_code)
        if status_code == 429:
            retry_after = None
            header = response.headers.get("retry-after")
            if header is not None:
                try:
                    retry_after = float(header)
                except ValueError:
                    retry_after = None
            return RateLimitError(detail, status_code=status_code, retry_after=retry_after)
        if status_code >= 500:
            return ServerError(detail, status_code=status_code)
        return ClawQuakeError(detail, status_code=status_code)

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
