"""
Shared test fixtures for ClawQuake test suite.

Provides:
- In-memory SQLite database session
- FastAPI TestClient with the app
- Mock RCON pool
- Helper functions for creating test users/bots
"""

import os
import sys
import pytest
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add orchestrator to path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))

# Set required env vars BEFORE importing anything from orchestrator
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only")
os.environ.setdefault("RCON_PASSWORD", "test-rcon-password")
os.environ.setdefault("INTERNAL_SECRET", "test-internal-secret")

from models import Base, UserDB, BotDB, MatchDB, QueueEntryDB, MatchParticipantDB


@pytest.fixture
def db_engine():
    """Create an in-memory SQLite engine for testing."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def db(db_engine):
    """Create a database session for testing."""
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def db_factory(db_engine):
    """Session factory for classes that create their own sessions."""
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    return TestSession


@pytest.fixture
def mock_rcon():
    """Mock RCON pool that returns canned responses."""
    pool = MagicMock()
    pool.get_available_server.return_value = {
        "id": "server-1",
        "host": "localhost",
        "port": 27960,
        "rcon_password": "test",
    }
    pool.send_rcon.return_value = "OK"
    pool.get_status.return_value = {
        "online": True,
        "players": [],
        "info": {"mapname": "q3dm17"},
    }
    return pool


# ── Test Data Helpers ────────────────────────────────────────────

def create_test_user(db, username="testuser", email="test@example.com") -> UserDB:
    """Create a test user in the database."""
    from auth import hash_password
    user = UserDB(
        username=username,
        email=email,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_test_bot(db, name="TestBot", owner_id=1, elo=1000.0) -> BotDB:
    """Create a test bot in the database."""
    bot = BotDB(name=name, owner_id=owner_id, elo=elo)
    db.add(bot)
    db.commit()
    db.refresh(bot)
    return bot


def queue_bot(db, bot_id: int, user_id: int) -> QueueEntryDB:
    """Add a bot to the matchmaking queue."""
    entry = QueueEntryDB(bot_id=bot_id, user_id=user_id, status="waiting")
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
