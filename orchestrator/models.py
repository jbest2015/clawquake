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


# Create tables
Base.metadata.create_all(bind=engine)
