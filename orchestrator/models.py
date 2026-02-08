from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, DateTime, Float, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./clawquake.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# SQLAlchemy models

class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_admin = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class MatchDB(Base):
    __tablename__ = "matches"
    id = Column(Integer, primary_key=True, index=True)
    map_name = Column(String, nullable=False)
    gametype = Column(String, default="ffa")
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    winner = Column(String, nullable=True)
    scores_json = Column(String, default="{}")


class BotDB(Base):
    __tablename__ = "bots"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    owner_id = Column(Integer, nullable=False)
    elo = Column(Float, default=1000.0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    kills = Column(Integer, default=0)
    deaths = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


# Pydantic schemas

class UserCreate(BaseModel):
    username: str
    email: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    is_admin: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MatchResponse(BaseModel):
    id: int
    map_name: str
    gametype: str
    started_at: datetime
    ended_at: Optional[datetime]
    winner: Optional[str]
    scores_json: str


class BotResponse(BaseModel):
    id: int
    name: str
    elo: float
    wins: int
    losses: int
    kills: int
    deaths: int


class ServerStatus(BaseModel):
    online: bool
    map_name: str
    players: list
    scores: dict
    fraglimit: int
    timelimit: int


# ── Queue & Match Participant Models (Claude — Batch 1) ──────

class QueueEntryDB(Base):
    __tablename__ = "queue"
    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, nullable=False)   # FK to bots.id
    user_id = Column(Integer, nullable=False)   # FK to users.id
    queued_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="waiting")  # waiting | matched | playing | done


class MatchParticipantDB(Base):
    __tablename__ = "match_participants"
    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, nullable=False)  # FK to matches.id
    bot_id = Column(Integer, nullable=False)    # FK to bots.id
    kills = Column(Integer, default=0)
    deaths = Column(Integer, default=0)
    score = Column(Integer, default=0)
    elo_before = Column(Float, default=1000.0)
    elo_after = Column(Float, default=1000.0)


# ── Queue & Match Pydantic Schemas ───────────────────────────

class QueueJoin(BaseModel):
    bot_id: int


class QueueStatus(BaseModel):
    position: int
    bot_name: str
    status: str
    queued_at: datetime


class MatchResultReport(BaseModel):
    """Internal: bot reports its match results."""
    match_id: int
    bot_name: str
    bot_id: int
    kills: int
    deaths: int
    duration_seconds: float
    strategy_name: str = ""
    strategy_version: str = ""


class MatchDetailResponse(BaseModel):
    id: int
    map_name: str
    gametype: str
    started_at: datetime
    ended_at: Optional[datetime]
    winner: Optional[str]
    duration_seconds: Optional[float] = None
    participants: list[dict] = []


# Create tables
Base.metadata.create_all(bind=engine)


# ── API Key Models (Codex — Batch 1) ───────────────────────────

class ApiKeyDB(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    name = Column(String, nullable=False, default="default")
    key_hash = Column(String, nullable=False, unique=True, index=True)
    key_prefix = Column(String, nullable=False, default="cq_")
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used = Column(DateTime, nullable=True)
    is_active = Column(Integer, default=1)
    expires_at = Column(DateTime, nullable=True)  # None = never expires


# ── API Key & Bot Registration Schemas ──────────────────────────

class ApiKeyCreate(BaseModel):
    name: str = "default"
    expires_in_days: Optional[int] = None  # None = never expires


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    created_at: datetime
    last_used: Optional[datetime]
    is_active: bool
    expires_at: Optional[datetime] = None


class ApiKeyCreated(BaseModel):
    id: int
    name: str
    key: str
    key_prefix: str
    created_at: datetime


class BotRegister(BaseModel):
    name: str


# Ensure appended models are included even if create_all above already ran.
Base.metadata.create_all(bind=engine)
