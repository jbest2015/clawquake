"""
Error handling tests for sdk.clawquake_sdk.
"""

import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sdk.clawquake_sdk import (
    AuthenticationError,
    ClawQuakeClient,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ServerError,
)


def make_response(status: int, payload: dict | None = None, headers: dict | None = None) -> httpx.Response:
    req = httpx.Request("GET", "http://test.local/api/status")
    return httpx.Response(status, json=payload or {"detail": "err"}, headers=headers, request=req)


def make_http_error(status: int, detail: str = "err", headers: dict | None = None) -> httpx.HTTPStatusError:
    response = make_response(status, {"detail": detail}, headers=headers)
    return httpx.HTTPStatusError("boom", request=response.request, response=response)


def test_authentication_error(monkeypatch):
    client = ClawQuakeClient("http://test.local")

    def fake_request(*args, **kwargs):
        raise make_http_error(401, "Invalid token")

    monkeypatch.setattr(client._http, "request", fake_request)
    with pytest.raises(AuthenticationError):
        client.status()


def test_forbidden_error(monkeypatch):
    client = ClawQuakeClient("http://test.local")

    def fake_request(*args, **kwargs):
        raise make_http_error(403, "Forbidden")

    monkeypatch.setattr(client._http, "request", fake_request)
    with pytest.raises(ForbiddenError):
        client.status()


def test_not_found_error(monkeypatch):
    client = ClawQuakeClient("http://test.local")

    def fake_request(*args, **kwargs):
        raise make_http_error(404, "Missing")

    monkeypatch.setattr(client._http, "request", fake_request)
    with pytest.raises(NotFoundError):
        client.get_match(999)


def test_conflict_error(monkeypatch):
    client = ClawQuakeClient("http://test.local")

    def fake_request(*args, **kwargs):
        raise make_http_error(409, "Bot name already taken")

    monkeypatch.setattr(client._http, "request", fake_request)
    with pytest.raises(ConflictError):
        client.register_bot("ExistingBot")


def test_rate_limit_error_includes_retry_after(monkeypatch):
    client = ClawQuakeClient("http://test.local", max_retries=0)

    def fake_request(*args, **kwargs):
        raise make_http_error(429, "Rate limit exceeded", headers={"retry-after": "2"})

    monkeypatch.setattr(client._http, "request", fake_request)
    with pytest.raises(RateLimitError) as err:
        client.status()
    assert err.value.retry_after == 2.0


def test_server_error(monkeypatch):
    client = ClawQuakeClient("http://test.local")

    def fake_request(*args, **kwargs):
        raise make_http_error(500, "Internal error")

    monkeypatch.setattr(client._http, "request", fake_request)
    with pytest.raises(ServerError):
        client.status()


def test_retry_503_then_success(monkeypatch):
    client = ClawQuakeClient("http://test.local", max_retries=2, backoff_base=0.0)
    calls = {"count": 0}

    def fake_request(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 2:
            raise make_http_error(503, "Try later")
        return make_response(200, {"status": "ok"})

    monkeypatch.setattr(client._http, "request", fake_request)
    monkeypatch.setattr(client, "_sleep", lambda seconds: None)

    data = client.status()
    assert data["status"] == "ok"
    assert calls["count"] == 2


def test_retry_429_exhausted_raises(monkeypatch):
    client = ClawQuakeClient("http://test.local", max_retries=1, backoff_base=0.0)
    calls = {"count": 0}

    def fake_request(*args, **kwargs):
        calls["count"] += 1
        raise make_http_error(429, "Slow down", headers={"retry-after": "0"})

    monkeypatch.setattr(client._http, "request", fake_request)
    monkeypatch.setattr(client, "_sleep", lambda seconds: None)

    with pytest.raises(RateLimitError):
        client.status()
    assert calls["count"] == 2
