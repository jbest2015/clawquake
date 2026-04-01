"""
API tests for auth, API keys, bots, and queue endpoints.
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))

from auth import get_db as auth_get_db
from main import app
from main import get_db as main_get_db
from models import Base
from routes_bots import get_db as bots_get_db
from routes_keys import get_db as keys_get_db
from routes_queue import get_db as queue_get_db


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[auth_get_db] = override_get_db
    app.dependency_overrides[main_get_db] = override_get_db
    app.dependency_overrides[bots_get_db] = override_get_db
    app.dependency_overrides[keys_get_db] = override_get_db
    app.dependency_overrides[queue_get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def register_user(client: TestClient, username: str, email: str) -> dict:
    res = client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": "testpass123"},
    )
    assert res.status_code == 200
    return res.json()


def login_user(client: TestClient, username: str, password: str = "testpass123") -> dict:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200
    return res.json()


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create_key(client: TestClient, token: str, name: str = "default") -> dict:
    res = client.post("/api/keys", json={"name": name}, headers=bearer(token))
    assert res.status_code == 200
    return res.json()


def create_bot(client: TestClient, token: str, name: str, strategy: str = "default") -> dict:
    res = client.post("/api/bots", json={"name": name, "strategy": strategy}, headers=bearer(token))
    assert res.status_code == 200
    return res.json()


def test_register_user(client: TestClient):
    data = register_user(client, "alice", "alice@example.com")
    assert data["access_token"]
    assert data["token_type"] == "bearer"


def test_login_user(client: TestClient):
    register_user(client, "bob", "bob@example.com")
    data = login_user(client, "bob")
    assert data["access_token"]
    assert data["token_type"] == "bearer"


def test_create_api_key(client: TestClient):
    token = register_user(client, "carl", "carl@example.com")["access_token"]
    data = create_key(client, token, "runner")
    assert data["name"] == "runner"
    assert data["key"].startswith("cq_")
    assert len(data["key"]) == 43
    assert data["key_prefix"] == data["key"][:8]


def test_list_api_keys(client: TestClient):
    token = register_user(client, "dina", "dina@example.com")["access_token"]
    created = create_key(client, token, "ci")
    res = client.get("/api/keys", headers=bearer(token))
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["name"] == "ci"
    assert data[0]["key_prefix"] == created["key_prefix"]
    assert "key" not in data[0]


def test_delete_api_key(client: TestClient):
    token = register_user(client, "ed", "ed@example.com")["access_token"]
    created = create_key(client, token, "old")
    res = client.delete(f"/api/keys/{created['id']}", headers=bearer(token))
    assert res.status_code == 200
    assert res.json()["deleted"] is True


def test_auth_with_api_key(client: TestClient):
    token = register_user(client, "faye", "faye@example.com")["access_token"]
    create_bot(client, token, "FayeBot")
    key = create_key(client, token, "agent")
    res = client.get("/api/bots", headers={"X-API-Key": key["key"]})
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["name"] == "FayeBot"


def test_register_bot(client: TestClient):
    token = register_user(client, "gina", "gina@example.com")["access_token"]
    res = client.post("/api/bots", json={"name": "GinaBot", "strategy": "codex"}, headers=bearer(token))
    assert res.status_code == 200
    assert res.json()["name"] == "GinaBot"
    assert res.json()["strategy"] == "codex"


def test_register_bot_invalid_strategy(client: TestClient):
    token = register_user(client, "gwen", "gwen@example.com")["access_token"]
    res = client.post("/api/bots", json={"name": "GwenBot", "strategy": "missing_strategy"}, headers=bearer(token))
    assert res.status_code == 400


def test_register_bot_duplicate_name(client: TestClient):
    t1 = register_user(client, "hank", "hank@example.com")["access_token"]
    t2 = register_user(client, "ivy", "ivy@example.com")["access_token"]
    create_bot(client, t1, "SharedBot")
    res = client.post("/api/bots", json={"name": "SharedBot"}, headers=bearer(t2))
    assert res.status_code == 400


def test_list_bots(client: TestClient):
    t1 = register_user(client, "joel", "joel@example.com")["access_token"]
    t2 = register_user(client, "kate", "kate@example.com")["access_token"]
    create_bot(client, t1, "JoelBot", strategy="codex")
    create_bot(client, t2, "KateBot")
    res = client.get("/api/bots", headers=bearer(t1))
    assert res.status_code == 200
    assert [b["name"] for b in res.json()] == ["JoelBot"]
    assert res.json()[0]["strategy"] == "codex"


def test_update_bot_strategy(client: TestClient):
    token = register_user(client, "lara", "lara@example.com")["access_token"]
    bot = create_bot(client, token, "LaraBot")
    res = client.patch(f"/api/bots/{bot['id']}", json={"strategy": "codex"}, headers=bearer(token))
    assert res.status_code == 200
    assert res.json()["strategy"] == "codex"


def test_update_bot_strategy_requires_owner(client: TestClient):
    owner_token = register_user(client, "milo", "milo@example.com")["access_token"]
    other_token = register_user(client, "nina", "nina@example.com")["access_token"]
    bot = create_bot(client, owner_token, "MiloBot")
    res = client.patch(f"/api/bots/{bot['id']}", json={"strategy": "codex"}, headers=bearer(other_token))
    assert res.status_code == 403


def test_join_queue(client: TestClient):
    token = register_user(client, "liam", "liam@example.com")["access_token"]
    bot = create_bot(client, token, "LiamBot")
    res = client.post("/api/queue/join", json={"bot_id": bot["id"]}, headers=bearer(token))
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "waiting"
    assert data["bot_name"] == "LiamBot"
    assert data["position"] == 1


def test_join_queue_not_own_bot(client: TestClient):
    owner_token = register_user(client, "maya", "maya@example.com")["access_token"]
    other_token = register_user(client, "nora", "nora@example.com")["access_token"]
    bot = create_bot(client, owner_token, "MayaBot")
    res = client.post("/api/queue/join", json={"bot_id": bot["id"]}, headers=bearer(other_token))
    assert res.status_code == 403


def test_leave_queue(client: TestClient):
    token = register_user(client, "omar", "omar@example.com")["access_token"]
    bot = create_bot(client, token, "OmarBot")
    client.post("/api/queue/join", json={"bot_id": bot["id"]}, headers=bearer(token))
    res = client.delete(f"/api/queue/leave?bot_id={bot['id']}", headers=bearer(token))
    assert res.status_code == 200
    assert res.json()["left"] is True


def test_queue_status(client: TestClient):
    t1 = register_user(client, "pia", "pia@example.com")["access_token"]
    t2 = register_user(client, "quinn", "quinn@example.com")["access_token"]
    b1 = create_bot(client, t1, "PiaBot")
    b2 = create_bot(client, t2, "QuinnBot")
    client.post("/api/queue/join", json={"bot_id": b1["id"]}, headers=bearer(t1))
    client.post("/api/queue/join", json={"bot_id": b2["id"]}, headers=bearer(t2))
    res = client.get(f"/api/queue/status?bot_id={b2['id']}", headers=bearer(t2))
    assert res.status_code == 200
    assert res.json()["position"] == 2


def test_create_agent_registration(client: TestClient):
    token = register_user(client, "ria", "ria@example.com")["access_token"]
    bot = create_bot(client, token, "RiaBot", strategy="codex")

    res = client.post(
        f"/api/bots/{bot['id']}/agent-registrations",
        json={"name": "primary"},
        headers=bearer(token),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["bot_id"] == bot["id"]
    assert data["name"] == "primary"
    assert data["agent_key"].startswith("cq_")
    assert "/getting-started?" in data["invite_url"]
    assert "agent_key=" in data["invite_url"]


def test_list_agent_registrations(client: TestClient):
    token = register_user(client, "sara", "sara@example.com")["access_token"]
    bot = create_bot(client, token, "SaraBot")
    client.post(
        f"/api/bots/{bot['id']}/agent-registrations",
        json={"name": "primary"},
        headers=bearer(token),
    )

    res = client.get(f"/api/bots/{bot['id']}/agent-registrations", headers=bearer(token))
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["bot_id"] == bot["id"]
    assert data[0]["status"] == "active"


def test_revoke_agent_registration(client: TestClient):
    token = register_user(client, "tess", "tess@example.com")["access_token"]
    bot = create_bot(client, token, "TessBot")
    created = client.post(
        f"/api/bots/{bot['id']}/agent-registrations",
        json={"name": "primary"},
        headers=bearer(token),
    ).json()

    res = client.delete(f"/api/agent-registrations/{created['id']}", headers=bearer(token))
    assert res.status_code == 200
    assert res.json()["revoked"] is True

    res = client.get(f"/api/bots/{bot['id']}/agent-registrations", headers=bearer(token))
    assert res.status_code == 200
    assert res.json() == []


def test_connect_agent_link(client: TestClient):
    token = register_user(client, "uma", "uma@example.com")["access_token"]
    bot = create_bot(client, token, "UmaBot")
    created = client.post(
        f"/api/bots/{bot['id']}/agent-registrations",
        json={"name": "primary"},
        headers=bearer(token),
    ).json()

    res = client.get("/api/agent/connect", params={"agent_key": created["agent_key"]})
    assert res.status_code == 200
    data = res.json()
    assert data["bot_id"] == bot["id"]
    assert data["observe_url"].startswith("http://testserver/api/agent/observe")
    assert f"bot_id={bot['id']}" in data["observe_url"]
    assert data["act_url"].startswith("http://testserver/api/agent/act")
    assert data["stream_url"].startswith("ws://testserver/api/agent/stream")
    assert "agent_key=" in data["stream_url"]


def test_tournament_creator_can_start(client: TestClient):
    creator = register_user(client, "vera", "vera@example.com")["access_token"]
    other = register_user(client, "walt", "walt@example.com")["access_token"]
    creator_bot = create_bot(client, creator, "VeraBot")
    other_bot = create_bot(client, other, "WaltBot")

    created = client.post(
        "/api/tournaments",
        json={"name": "Spring Cup", "format": "single_elim"},
        headers=bearer(creator),
    )
    assert created.status_code == 200
    tournament = created.json()
    assert tournament["created_by_user_id"] is not None

    tid = tournament["id"]
    assert client.post(
        f"/api/tournaments/{tid}/join",
        json={"bot_id": creator_bot["id"]},
        headers=bearer(creator),
    ).status_code == 200
    assert client.post(
        f"/api/tournaments/{tid}/join",
        json={"bot_id": other_bot["id"]},
        headers=bearer(other),
    ).status_code == 200

    res = client.post(f"/api/tournaments/{tid}/start", headers=bearer(creator))
    assert res.status_code == 200
    assert res.json()["started"] is True


def test_non_owner_cannot_start_tournament(client: TestClient):
    creator = register_user(client, "xena", "xena@example.com")["access_token"]
    other = register_user(client, "yara", "yara@example.com")["access_token"]
    creator_bot = create_bot(client, creator, "XenaBot")
    other_bot = create_bot(client, other, "YaraBot")

    tid = client.post(
        "/api/tournaments",
        json={"name": "Owner Cup", "format": "single_elim"},
        headers=bearer(creator),
    ).json()["id"]

    client.post(
        f"/api/tournaments/{tid}/join",
        json={"bot_id": creator_bot["id"]},
        headers=bearer(creator),
    )
    client.post(
        f"/api/tournaments/{tid}/join",
        json={"bot_id": other_bot["id"]},
        headers=bearer(other),
    )

    res = client.post(f"/api/tournaments/{tid}/start", headers=bearer(other))
    assert res.status_code == 403


def test_cannot_join_tournament_after_start(client: TestClient):
    creator = register_user(client, "zane", "zane@example.com")["access_token"]
    other = register_user(client, "abby", "abby@example.com")["access_token"]
    creator_bot = create_bot(client, creator, "ZaneBot")
    other_bot = create_bot(client, other, "AbbyBot")

    tid = client.post(
        "/api/tournaments",
        json={"name": "Closed Cup", "format": "single_elim"},
        headers=bearer(creator),
    ).json()["id"]

    assert client.post(
        f"/api/tournaments/{tid}/join",
        json={"bot_id": creator_bot["id"]},
        headers=bearer(creator),
    ).status_code == 200
    assert client.post(
        f"/api/tournaments/{tid}/join",
        json={"bot_id": other_bot["id"]},
        headers=bearer(other),
    ).status_code == 200
    assert client.post(f"/api/tournaments/{tid}/start", headers=bearer(creator)).status_code == 200

    late_bot = create_bot(client, other, "LateBot")
    res = client.post(
        f"/api/tournaments/{tid}/join",
        json={"bot_id": late_bot["id"]},
        headers=bearer(other),
    )
    assert res.status_code == 400
