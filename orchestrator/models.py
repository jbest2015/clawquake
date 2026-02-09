import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, DateTime, Float, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# DB path: honour DATABASE_URL env var, or put in /app/data/ if that dir exists (Docker named volume)
_db_dir = os.environ.get("DATABASE_DIR", "")
if not _db_dir and os.path.isdir("/app/data"):
    _db_dir = "/app/data"
if _db_dir:
    Path(_db_dir).mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite:///{_db_dir}/clawquake.db"
else:
    DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./clawquake.db")

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



# ── Tournament Models (Anti-Gravity — Batch 3) ──────────────

class TournamentDB(Base):
    __tablename__ = "tournaments"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    format = Column(String, default="single_elim") # single_elim, double_elim
    status = Column(String, default="pending") # pending, active, completed
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    winner_bot_id = Column(Integer, nullable=True) # FK bots.id
    current_round = Column(Integer, default=0)

class TournamentParticipantDB(Base):
    __tablename__ = "tournament_participants"
    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(Integer, nullable=False, index=True) # FK tournaments.id
    bot_id = Column(Integer, nullable=False) # FK bots.id
    seed = Column(Integer, nullable=True)
    eliminated = Column(Integer, default=0) # boolean
    rank = Column(Integer, nullable=True) # Final placement

class TournamentMatchDB(Base):
    __tablename__ = "tournament_matches"
    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(Integer, nullable=False, index=True) # FK tournaments.id
    round_num = Column(Integer, nullable=False)
    match_num = Column(Integer, nullable=False) # ID within round
    player1_bot_id = Column(Integer, nullable=True) # None = TBD/Bye
    player2_bot_id = Column(Integer, nullable=True)
    winner_bot_id = Column(Integer, nullable=True)
    next_match_id = Column(Integer, nullable=True) # For bracket linking (optional)
    game_match_id = Column(Integer, nullable=True) # FK matches.id (actual game)

# ── Tournament Pydantic Schemas ─────────────────────────────

class TournamentCreate(BaseModel):
    name: str
    format: str = "single_elim"
    seed_by_elo: bool = True

class TournamentJoin(BaseModel):
    bot_id: int

class TournamentResponse(BaseModel):
    id: int
    name: str
    format: str
    status: str
    participant_count: int
    current_round: int
    winner_bot_id: Optional[int]

# ── Adaptive Learner DB (Anti-Gravity — Batch 4) ────────────

class OpponentProfileDB(Base):
    __tablename__ = "opponent_profiles"
    id = Column(Integer, primary_key=True, index=True)
    opponent_name = Column(String, unique=True, index=True, nullable=False)
    weapon_counts = Column(String, default="{}") # JSON
    damage_taken = Column(String, default="{}") # JSON
    engagement_range_avg = Column(Float, default=0.0)
    games_analyzed = Column(Integer, default=0)
    last_updated = Column(DateTime, default=datetime.utcnow)
    ttl_days = Column(Integer, default=30)

# ── Create all tables (must be AFTER all model definitions) ───
Base.metadata.create_all(bind=engine)
