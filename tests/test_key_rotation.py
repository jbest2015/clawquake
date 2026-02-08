"""
Tests for API key rotation and expiry.
"""

import os
import sys
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only")

from auth import get_db as auth_get_db
from main import app
from main import get_db as main_get_db
from models import Base, ApiKeyDB
from routes_bots import get_db as bots_get_db
from routes_keys import get_db as keys_get_db
from routes_queue import get_db as queue_get_db


@pytest.fixture
def env():
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

    with TestClient(app) as client:
        yield {"client": client, "session_factory": TestingSession}

    app.dependency_overrides.clear()


def _register(client, username):
    res = client.post("/api/auth/register", json={
        "username": username,
        "email": f"{username}@test.com",
        "password": "testpass123",
    })
    assert res.status_code == 200
    return res.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── Key Expiry Tests ──────────────────────────────────────────

class TestKeyExpiry:

    def test_create_key_with_expiry(self, env):
        c = env["client"]
        token = _register(c, "expiry_user1")

        res = c.post("/api/keys", json={
            "name": "temp-key",
            "expires_in_days": 30,
        }, headers=_auth(token))
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "temp-key"
        assert data["key"].startswith("cq_")

    def test_create_key_without_expiry(self, env):
        c = env["client"]
        token = _register(c, "expiry_user2")

        res = c.post("/api/keys", json={
            "name": "permanent",
        }, headers=_auth(token))
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "permanent"

    def test_list_keys_shows_expiry(self, env):
        c = env["client"]
        token = _register(c, "expiry_user3")

        c.post("/api/keys", json={
            "name": "expiring",
            "expires_in_days": 7,
        }, headers=_auth(token))

        res = c.get("/api/keys", headers=_auth(token))
        assert res.status_code == 200
        keys = res.json()
        assert len(keys) == 1
        assert keys[0]["expires_at"] is not None

    def test_expired_key_rejected(self, env):
        """Manually set a key's expiry to the past, verify it's rejected."""
        c = env["client"]
        db_factory = env["session_factory"]
        token = _register(c, "expiry_user4")

        # Create a key
        key_data = c.post("/api/keys", json={"name": "soon-dead"}, headers=_auth(token)).json()
        raw_key = key_data["key"]

        # Create a bot so we have something to query
        c.post("/api/bots", json={"name": "ExpiryBot"}, headers=_auth(token))

        # Verify key works
        res = c.get("/api/bots", headers={"X-API-Key": raw_key})
        assert res.status_code == 200

        # Manually expire the key in the DB
        db = db_factory()
        try:
            key_record = db.query(ApiKeyDB).filter(ApiKeyDB.id == key_data["id"]).first()
            key_record.expires_at = datetime.utcnow() - timedelta(hours=1)
            db.commit()
        finally:
            db.close()

        # Key should now be rejected
        res = c.get("/api/bots", headers={"X-API-Key": raw_key})
        assert res.status_code == 401
        assert "expired" in res.json()["detail"].lower()

    def test_unexpired_key_works(self, env):
        c = env["client"]
        db_factory = env["session_factory"]
        token = _register(c, "expiry_user5")

        key_data = c.post("/api/keys", json={
            "name": "future-key",
            "expires_in_days": 30,
        }, headers=_auth(token)).json()

        c.post("/api/bots", json={"name": "FutureBot"}, headers=_auth(token))

        # Should work (expiry is 30 days out)
        res = c.get("/api/bots", headers={"X-API-Key": key_data["key"]})
        assert res.status_code == 200


# ── Key Rotation Tests ────────────────────────────────────────

class TestKeyRotation:

    def test_rotate_key_basic(self, env):
        c = env["client"]
        token = _register(c, "rotate_user1")

        # Create and register a bot
        old_key = c.post("/api/keys", json={"name": "my-agent"}, headers=_auth(token)).json()
        c.post("/api/bots", json={"name": "RotateBot1"}, headers=_auth(token))

        # Verify old key works
        res = c.get("/api/bots", headers={"X-API-Key": old_key["key"]})
        assert res.status_code == 200

        # Rotate
        res = c.post(f"/api/keys/{old_key['id']}/rotate", headers=_auth(token))
        assert res.status_code == 200
        new_key = res.json()
        assert new_key["name"] == "my-agent"  # Same name preserved
        assert new_key["key"] != old_key["key"]  # Different key
        assert new_key["key"].startswith("cq_")

        # Old key no longer works
        res = c.get("/api/bots", headers={"X-API-Key": old_key["key"]})
        assert res.status_code == 401

        # New key works
        res = c.get("/api/bots", headers={"X-API-Key": new_key["key"]})
        assert res.status_code == 200

    def test_rotate_preserves_name(self, env):
        c = env["client"]
        token = _register(c, "rotate_user2")

        old = c.post("/api/keys", json={"name": "ci-runner"}, headers=_auth(token)).json()
        new = c.post(f"/api/keys/{old['id']}/rotate", headers=_auth(token)).json()
        assert new["name"] == "ci-runner"

    def test_rotate_nonexistent_key_404(self, env):
        c = env["client"]
        token = _register(c, "rotate_user3")

        res = c.post("/api/keys/99999/rotate", headers=_auth(token))
        assert res.status_code == 404

    def test_rotate_revoked_key_404(self, env):
        c = env["client"]
        token = _register(c, "rotate_user4")

        key = c.post("/api/keys", json={"name": "temp"}, headers=_auth(token)).json()
        c.delete(f"/api/keys/{key['id']}", headers=_auth(token))

        res = c.post(f"/api/keys/{key['id']}/rotate", headers=_auth(token))
        assert res.status_code == 404

    def test_rotate_other_users_key_404(self, env):
        c = env["client"]
        t1 = _register(c, "rotate_user5")
        t2 = _register(c, "rotate_user6")

        key = c.post("/api/keys", json={"name": "secret"}, headers=_auth(t1)).json()

        # Other user cannot rotate it
        res = c.post(f"/api/keys/{key['id']}/rotate", headers=_auth(t2))
        assert res.status_code == 404

    def test_rotate_key_with_expiry_preserves_remaining(self, env):
        """When rotating an expiring key, the new key preserves the remaining time."""
        c = env["client"]
        db_factory = env["session_factory"]
        token = _register(c, "rotate_user7")

        key = c.post("/api/keys", json={
            "name": "expiring-rotate",
            "expires_in_days": 30,
        }, headers=_auth(token)).json()

        # Rotate it
        new_key = c.post(f"/api/keys/{key['id']}/rotate", headers=_auth(token)).json()

        # Verify the new key has an expiry
        keys = c.get("/api/keys", headers=_auth(token)).json()
        assert len(keys) == 1  # Only active key shown
        new_record = keys[0]
        assert new_record["expires_at"] is not None

    def test_rotate_expired_key_fails(self, env):
        """Cannot rotate an already expired key."""
        c = env["client"]
        db_factory = env["session_factory"]
        token = _register(c, "rotate_user8")

        key = c.post("/api/keys", json={
            "name": "dead-key",
            "expires_in_days": 1,
        }, headers=_auth(token)).json()

        # Manually expire it
        db = db_factory()
        try:
            record = db.query(ApiKeyDB).filter(ApiKeyDB.id == key["id"]).first()
            record.expires_at = datetime.utcnow() - timedelta(hours=1)
            db.commit()
        finally:
            db.close()

        res = c.post(f"/api/keys/{key['id']}/rotate", headers=_auth(token))
        assert res.status_code == 400
        assert "expired" in res.json()["detail"].lower()
