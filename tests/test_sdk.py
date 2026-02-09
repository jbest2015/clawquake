"""
Unit tests for sdk.clawquake_sdk with mocked HTTP calls.
"""

import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sdk.clawquake_sdk import ClawQuakeClient


def make_response(method: str, path: str, payload: dict | list, status_code: int = 200) -> httpx.Response:
    req = httpx.Request(method, f"http://test.local{path}")
    return httpx.Response(status_code=status_code, json=payload, request=req)


def test_register(monkeypatch):
    client = ClawQuakeClient("http://test.local")

    def fake_request(method, path, headers=None, **kwargs):
        assert method == "POST"
        assert path == "/api/auth/register"
        assert kwargs["json"]["username"] == "alice"
        return make_response(method, path, {"access_token": "jwt-1", "token_type": "bearer"})

    monkeypatch.setattr(client._http, "request", fake_request)
    data = client.register("alice", "a@example.com", "secret")
    assert data["access_token"] == "jwt-1"
    assert client.jwt_token == "jwt-1"


def test_login(monkeypatch):
    client = ClawQuakeClient("http://test.local")

    def fake_request(method, path, headers=None, **kwargs):
        assert method == "POST"
        assert path == "/api/auth/login"
        return make_response(method, path, {"access_token": "jwt-2", "token_type": "bearer"})

    monkeypatch.setattr(client._http, "request", fake_request)
    data = client.login("alice", "secret")
    assert data["access_token"] == "jwt-2"
    assert client.jwt_token == "jwt-2"


def test_create_key(monkeypatch):
    client = ClawQuakeClient("http://test.local", jwt_token="jwt")

    def fake_request(method, path, headers=None, **kwargs):
        assert method == "POST"
        assert path == "/api/keys"
        assert headers["Authorization"] == "Bearer jwt"
        return make_response(method, path, {"id": 1, "key": "cq_abc", "name": "runner", "key_prefix": "cq_abc"})

    monkeypatch.setattr(client._http, "request", fake_request)
    data = client.create_key("runner", expires_in_days=7)
    assert data["id"] == 1


def test_list_keys(monkeypatch):
    client = ClawQuakeClient("http://test.local", jwt_token="jwt")

    def fake_request(method, path, headers=None, **kwargs):
        assert method == "GET"
        assert path == "/api/keys"
        return make_response(method, path, [{"id": 1, "name": "runner", "key_prefix": "cq_abcd"}])

    monkeypatch.setattr(client._http, "request", fake_request)
    data = client.list_keys()
    assert len(data) == 1
    assert data[0]["name"] == "runner"


def test_rotate_key(monkeypatch):
    client = ClawQuakeClient("http://test.local", jwt_token="jwt")

    def fake_request(method, path, headers=None, **kwargs):
        assert method == "POST"
        assert path == "/api/keys/4/rotate"
        return make_response(method, path, {"id": 8, "key": "cq_new", "name": "old"})

    monkeypatch.setattr(client._http, "request", fake_request)
    data = client.rotate_key(4)
    assert data["id"] == 8


def test_register_bot(monkeypatch):
    client = ClawQuakeClient("http://test.local", jwt_token="jwt")

    def fake_request(method, path, headers=None, **kwargs):
        assert method == "POST"
        assert path == "/api/bots"
        assert kwargs["json"]["name"] == "MyBot"
        return make_response(method, path, {"id": 2, "name": "MyBot", "elo": 1000.0})

    monkeypatch.setattr(client._http, "request", fake_request)
    data = client.register_bot("MyBot")
    assert data["name"] == "MyBot"


def test_list_bots(monkeypatch):
    client = ClawQuakeClient("http://test.local", jwt_token="jwt")

    def fake_request(method, path, headers=None, **kwargs):
        assert method == "GET"
        assert path == "/api/bots"
        return make_response(method, path, [{"id": 1, "name": "Bot1"}, {"id": 2, "name": "Bot2"}])

    monkeypatch.setattr(client._http, "request", fake_request)
    data = client.list_bots()
    assert len(data) == 2


def test_join_queue(monkeypatch):
    client = ClawQuakeClient("http://test.local", jwt_token="jwt")

    def fake_request(method, path, headers=None, **kwargs):
        assert method == "POST"
        assert path == "/api/queue/join"
        assert kwargs["json"]["bot_id"] == 7
        return make_response(method, path, {"position": 1, "bot_name": "B", "status": "waiting"})

    monkeypatch.setattr(client._http, "request", fake_request)
    data = client.join_queue(7)
    assert data["status"] == "waiting"


def test_check_status(monkeypatch):
    client = ClawQuakeClient("http://test.local", jwt_token="jwt")

    def fake_request(method, path, headers=None, **kwargs):
        assert method == "GET"
        assert path == "/api/queue/status"
        assert kwargs["params"]["bot_id"] == 5
        return make_response(method, path, {"position": 2, "bot_name": "B", "status": "waiting"})

    monkeypatch.setattr(client._http, "request", fake_request)
    data = client.check_status(5)
    assert data["position"] == 2


def test_leave_queue(monkeypatch):
    client = ClawQuakeClient("http://test.local", jwt_token="jwt")

    def fake_request(method, path, headers=None, **kwargs):
        assert method == "DELETE"
        assert path == "/api/queue/leave"
        assert kwargs["params"]["bot_id"] == 3
        return make_response(method, path, {"left": True})

    monkeypatch.setattr(client._http, "request", fake_request)
    assert client.leave_queue(3) is True


def test_get_match(monkeypatch):
    client = ClawQuakeClient("http://test.local", jwt_token="jwt")

    def fake_request(method, path, headers=None, **kwargs):
        assert method == "GET"
        assert path == "/api/matches/11"
        return make_response(method, path, {"id": 11, "winner": "BotA", "participants": []})

    monkeypatch.setattr(client._http, "request", fake_request)
    data = client.get_match(11)
    assert data["id"] == 11


def test_health(monkeypatch):
    client = ClawQuakeClient("http://test.local")

    def fake_request(method, path, headers=None, **kwargs):
        assert method == "GET"
        assert path == "/api/health"
        return make_response(method, path, {"status": "ok"})

    monkeypatch.setattr(client._http, "request", fake_request)
    data = client.health()
    assert data["status"] == "ok"


def test_auth_header_apikey(monkeypatch):
    client = ClawQuakeClient("http://test.local", api_key="cq_secret")

    def fake_request(method, path, headers=None, **kwargs):
        assert headers["X-API-Key"] == "cq_secret"
        assert "Authorization" not in headers
        return make_response(method, path, {"status": "ok"})

    monkeypatch.setattr(client._http, "request", fake_request)
    client.status()


def test_auth_header_jwt(monkeypatch):
    client = ClawQuakeClient("http://test.local", jwt_token="jwt_token")

    def fake_request(method, path, headers=None, **kwargs):
        assert headers["Authorization"] == "Bearer jwt_token"
        assert "X-API-Key" not in headers
        return make_response(method, path, {"status": "ok"})

    monkeypatch.setattr(client._http, "request", fake_request)
    client.status()
