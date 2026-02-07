"""
ClawQuake Orchestrator — FastAPI service for auth, match control, and leaderboards.
"""

import json
import logging
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from auth import (
    get_db, hash_password, verify_password,
    create_access_token, get_current_user, require_admin,
)
from models import (
    UserDB, MatchDB, BotDB,
    UserCreate, UserLogin, UserResponse, TokenResponse,
    MatchResponse, BotResponse, ServerStatus,
)
from rcon import get_server_status, add_bot, change_map, server_say, send_rcon

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clawquake")

app = FastAPI(title="ClawQuake Orchestrator", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth Endpoints ──────────────────────────────────────────────

@app.post("/api/auth/register", response_model=TokenResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(UserDB).filter(UserDB.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    if db.query(UserDB).filter(UserDB.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    db_user = UserDB(
        username=user.username,
        email=user.email,
        hashed_password=hash_password(user.password),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    token = create_access_token({"sub": db_user.username})
    logger.info(f"User registered: {db_user.username}")
    return TokenResponse(access_token=token)


@app.post("/api/auth/login", response_model=TokenResponse)
def login(creds: UserLogin, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.username == creds.username).first()
    if not user or not verify_password(creds.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": user.username})
    logger.info(f"User login: {user.username}")
    return TokenResponse(access_token=token)


@app.get("/api/auth/me", response_model=UserResponse)
def me(user: UserDB = Depends(get_current_user)):
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_admin=bool(user.is_admin),
        created_at=user.created_at,
    )


# ── Public Status ───────────────────────────────────────────────

@app.get("/api/status")
def status():
    """Current server status — public endpoint."""
    data = get_server_status()
    if not data["online"]:
        return {"online": False, "message": "Game server offline"}

    info = data.get("info", {})
    return {
        "online": True,
        "map_name": info.get("mapname", "unknown"),
        "hostname": info.get("sv_hostname", "ClawQuake Arena"),
        "gametype": info.get("g_gametype", "0"),
        "fraglimit": info.get("fraglimit", "50"),
        "timelimit": info.get("timelimit", "15"),
        "players": data.get("players", []),
        "player_count": len(data.get("players", [])),
        "max_clients": info.get("sv_maxclients", "16"),
    }


# ── Leaderboard ─────────────────────────────────────────────────

@app.get("/api/leaderboard", response_model=list[BotResponse])
def leaderboard(
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bots = db.query(BotDB).order_by(BotDB.elo.desc()).limit(50).all()
    return [
        BotResponse(
            id=b.id, name=b.name, elo=b.elo,
            wins=b.wins, losses=b.losses,
            kills=b.kills, deaths=b.deaths,
        )
        for b in bots
    ]


# ── Match History ───────────────────────────────────────────────

@app.get("/api/matches", response_model=list[MatchResponse])
def matches(
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    results = db.query(MatchDB).order_by(MatchDB.started_at.desc()).limit(50).all()
    return [
        MatchResponse(
            id=m.id, map_name=m.map_name, gametype=m.gametype,
            started_at=m.started_at, ended_at=m.ended_at,
            winner=m.winner, scores_json=m.scores_json,
        )
        for m in results
    ]


# ── Admin: Match Control ────────────────────────────────────────

@app.post("/api/admin/match/start")
def start_match(
    map_name: str = "q3dm17",
    admin: UserDB = Depends(require_admin),
    db: Session = Depends(get_db),
):
    change_map(map_name)
    match = MatchDB(map_name=map_name, gametype="ffa")
    db.add(match)
    db.commit()
    db.refresh(match)
    logger.info(f"Match started: {map_name} (by {admin.username})")
    return {"match_id": match.id, "map": map_name}


@app.post("/api/admin/addbot")
def admin_add_bot(
    name: str = "Sarge",
    skill: int = 3,
    admin: UserDB = Depends(require_admin),
):
    result = add_bot(name, skill)
    return {"result": result, "bot": name, "skill": skill}


@app.post("/api/admin/say")
def admin_say(message: str, admin: UserDB = Depends(require_admin)):
    result = server_say(message)
    return {"result": result}


@app.post("/api/admin/rcon")
def admin_rcon(command: str, admin: UserDB = Depends(require_admin)):
    result = send_rcon(command)
    return {"result": result}


# ── Health ──────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "clawquake-orchestrator"}
