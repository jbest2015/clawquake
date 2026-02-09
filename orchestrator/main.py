"""
ClawQuake Orchestrator — FastAPI service for auth, match control, and leaderboards.
"""

import asyncio
import json
import logging
import os
from contextlib import suppress
from datetime import datetime
from queue import SimpleQueue

from fastapi import FastAPI, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from auth import (
    get_db, hash_password, verify_password,
    create_access_token, get_current_user, require_admin,
)
from models import (
    UserDB, MatchDB, BotDB, MatchParticipantDB, QueueEntryDB, SessionLocal,
    UserCreate, UserLogin, UserResponse, TokenResponse,
    MatchResponse, BotResponse, ServerStatus,
    MatchResultReport, MatchDetailResponse,
)
from routes_bots import router as bots_router
from routes_keys import router as keys_router
from routes_queue import router as queue_router
from rcon import get_server_status, add_bot, change_map, server_say, send_rcon
from rcon_pool import RconPool
from process_manager import BotProcessManager
from matchmaker import MatchMaker
from websocket_hub import WebSocketHub
from tournament.bracket import TournamentBracket
from models import (
    TournamentCreate, TournamentJoin, TournamentResponse
)
from ai_agent_interface import router as ai_agent_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clawquake")


# ── Server Configuration ──────────────────────────────────────────

def _load_server_list() -> list[dict]:
    """Load game server list from GAME_SERVERS env var (JSON array)."""
    raw = os.environ.get("GAME_SERVERS", "")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid GAME_SERVERS JSON, using defaults")

    # Fallback: single server from legacy env vars
    host = os.environ.get("GAME_SERVER_HOST", "localhost")
    port = int(os.environ.get("GAME_SERVER_PORT", "27960"))
    rcon_pw = os.environ.get("RCON_PASSWORD", "")
    return [{"id": "server-1", "host": host, "port": port, "rcon_password": rcon_pw}]


# Initialize infrastructure (lazy — only when env vars are set)
_server_list = _load_server_list()
rcon_pool = RconPool(_server_list)

_internal_secret = os.environ.get("INTERNAL_SECRET", "")
_orchestrator_url = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8000")

process_manager = BotProcessManager(
    orchestrator_url=_orchestrator_url,
    internal_secret=_internal_secret,
)

matchmaker = MatchMaker(
    process_manager=process_manager,
    rcon_pool=rcon_pool,
)
websocket_hub = WebSocketHub()
event_queue: SimpleQueue[tuple[str, dict]] = SimpleQueue()
websocket_publisher_task: asyncio.Task | None = None


app = FastAPI(title="ClawQuake Orchestrator", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bots_router)
app.include_router(keys_router)
app.include_router(queue_router)
app.include_router(ai_agent_router)


def _status_payload() -> dict:
    """Current server status payload used by HTTP and WebSocket paths."""
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


def _queue_payload() -> dict:
    """Queue and active match summary for live clients."""
    db = SessionLocal()
    try:
        waiting = db.query(BotDB).count()
        waiting_entries = (
            db.query(QueueEntryDB)
            .filter(QueueEntryDB.status == "waiting")
            .count()
        )
        active = process_manager.active_matches()
        return {
            "waiting_entries": int(waiting_entries),
            "registered_bots": int(waiting),
            "active_match_count": len(active),
            "active_matches": active,
        }
    finally:
        db.close()


async def _websocket_publish_loop():
    """Pushes live status/queue updates and queued events to connected clients."""
    previous_active: set[int] = set()
    while True:
        if websocket_hub.connection_count == 0:
            await asyncio.sleep(1.0)
            continue

        # Drain queued events first.
        while not event_queue.empty():
            event_type, payload = event_queue.get_nowait()
            await websocket_hub.broadcast(event_type, payload)

        queue_data = _queue_payload()
        await websocket_hub.broadcast("status_update", _status_payload())
        await websocket_hub.broadcast("queue_update", queue_data)

        active_ids = {int(m.get("match_id")) for m in queue_data["active_matches"] if "match_id" in m}
        started = active_ids - previous_active
        ended = previous_active - active_ids
        for match_id in started:
            await websocket_hub.broadcast("match_started", {"match_id": match_id})
        for match_id in ended:
            await websocket_hub.broadcast("match_ended", {"match_id": match_id})
        previous_active = active_ids

        await asyncio.sleep(3.0)


@app.on_event("startup")
async def _startup_websocket_publisher():
    global websocket_publisher_task
    if websocket_publisher_task is None or websocket_publisher_task.done():
        websocket_publisher_task = asyncio.create_task(_websocket_publish_loop())


@app.on_event("shutdown")
async def _shutdown_websocket_publisher():
    global websocket_publisher_task
    if websocket_publisher_task:
        websocket_publisher_task.cancel()
        with suppress(asyncio.CancelledError):
            await websocket_publisher_task
        websocket_publisher_task = None


@app.websocket("/ws/events")
async def websocket_events(ws: WebSocket):
    await websocket_hub.connect(ws)
    await ws.send_json({"event_type": "connected", "data": {"ok": True}})
    try:
        while True:
            msg = await ws.receive_text()
            if msg.lower() == "ping":
                await ws.send_json({"event_type": "pong", "data": {"ok": True}})
    except WebSocketDisconnect:
        await websocket_hub.disconnect(ws)
    except Exception:
        await websocket_hub.disconnect(ws)


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
    return _status_payload()


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


# ── Admin: Active Matches (Batch 2) ────────────────────────────

@app.get("/api/admin/matches/active")
def admin_active_matches(admin: UserDB = Depends(require_admin)):
    """List all active matches with process status."""
    return {"matches": process_manager.active_matches()}


@app.get("/api/admin/servers")
def admin_server_list(admin: UserDB = Depends(require_admin)):
    """List all game servers with status."""
    return {"servers": rcon_pool.list_all()}


# ── Internal: Match Reporting (Claude — Batch 1) ──────────────

INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "")


@app.post("/api/internal/match/report")
def internal_match_report(
    report: MatchResultReport,
    x_internal_secret: str = Header(..., alias="X-Internal-Secret"),
    db: Session = Depends(get_db),
):
    """Bot agent_runner POSTs results here after a round ends."""
    if not INTERNAL_SECRET or x_internal_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Invalid internal secret")

    # Find the participant record and update it
    participant = (
        db.query(MatchParticipantDB)
        .filter(
            MatchParticipantDB.match_id == report.match_id,
            MatchParticipantDB.bot_id == report.bot_id,
        )
        .first()
    )
    if not participant:
        raise HTTPException(status_code=404, detail="Match participant not found")

    participant.kills = report.kills
    participant.deaths = report.deaths
    participant.score = report.kills - report.deaths
    db.commit()

    logger.info(
        f"Match {report.match_id}: {report.bot_name} reported "
        f"K={report.kills} D={report.deaths}"
    )
    event_queue.put((
        "kill_event",
        {
            "match_id": report.match_id,
            "bot_id": report.bot_id,
            "bot_name": report.bot_name,
            "kills": report.kills,
            "deaths": report.deaths,
        },
    ))
    return {"ok": True}


@app.get("/api/matches/{match_id}")
def get_match_detail(
    match_id: int,
    db: Session = Depends(get_db),
):
    """Get match details with all participants."""
    match = db.query(MatchDB).filter(MatchDB.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    participants = (
        db.query(MatchParticipantDB)
        .filter(MatchParticipantDB.match_id == match_id)
        .all()
    )

    participant_data = []
    for p in participants:
        bot = db.query(BotDB).filter(BotDB.id == p.bot_id).first()
        participant_data.append({
            "bot_id": p.bot_id,
            "bot_name": bot.name if bot else "unknown",
            "kills": p.kills,
            "deaths": p.deaths,
            "score": p.score,
            "elo_before": p.elo_before,
            "elo_after": p.elo_after,
            "elo_change": round(p.elo_after - p.elo_before, 2),
        })

    duration = None
    if match.ended_at and match.started_at:
        duration = (match.ended_at - match.started_at).total_seconds()

    return MatchDetailResponse(
        id=match.id,
        map_name=match.map_name,
        gametype=match.gametype,
        started_at=match.started_at,
        ended_at=match.ended_at,
        winner=match.winner,
        duration_seconds=duration,
        participants=participant_data,
    )



# ── Tournament Endpoints (Anti-Gravity — Batch 3) ──────────────

@app.post("/api/tournaments", response_model=TournamentResponse)
def create_tournament(
    t: TournamentCreate,
    user: UserDB = Depends(get_current_user), # Any user can create
    db: Session = Depends(get_db),
):
    system = TournamentBracket(db)
    bracket = system.create_tournament(t.name, t.format)
    return TournamentResponse(
        id=bracket.id, name=bracket.name, format=bracket.format,
        status="pending", participant_count=0, current_round=0,
        winner_bot_id=None
    )

@app.post("/api/tournaments/{tid}/join")
def join_tournament(
    tid: int,
    join: TournamentJoin,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    system = TournamentBracket(db)
    bot = db.query(BotDB).filter_by(id=join.bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
        
    # Check ownership
    if bot.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Not your bot")
        
    success = system.add_participant(tid, join.bot_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to join (already present or tournament active)")
    return {"joined": True, "bot": bot.name}

@app.post("/api/tournaments/{tid}/start")
def start_tournament(
    tid: int,
    user: UserDB = Depends(get_current_user), # Admin only? Or owner?
    db: Session = Depends(get_db),
):
    # check if user is admin or created the tournament? 
    # For now, require admin
    if not user.is_admin:
         raise HTTPException(status_code=403, detail="Admin required to start tournament")
         
    system = TournamentBracket(db)
    ok = system.start_tournament(tid)
    if not ok:
        raise HTTPException(status_code=400, detail="Could not start (not enough players or already started)")
    return {"started": True}

@app.get("/api/tournaments/{tid}")
def get_tournament(
    tid: int,
    db: Session = Depends(get_db),
):
    system = TournamentBracket(db)
    # Get tournament info
    from models import TournamentDB, TournamentParticipantDB
    t = db.query(TournamentDB).get(tid)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
        
    count = db.query(TournamentParticipantDB).filter_by(tournament_id=tid).count()
    bracket_data = system.get_bracket(tid)
    
    # Format matches for JSON
    rounds_json = {}
    for r_num, matches in bracket_data.items():
        m_list = []
        for m in matches:
            m_list.append({
                "match_id": m.id,
                "match_num": m.match_num,
                "p1": m.player1_bot_id,
                "p2": m.player2_bot_id,
                "winner": m.winner_bot_id,
                "next": m.next_match_id
            })
        rounds_json[r_num] = m_list
        
    return {
        "info": TournamentResponse(
             id=t.id, name=t.name, format=t.format, status=t.status,
             participant_count=count, current_round=t.current_round, 
             winner_bot_id=t.winner_bot_id
        ),
        "bracket": rounds_json
    }

@app.post("/api/tournaments/{tid}/matches/{mid}/result")
def record_tournament_match(
    tid: int, mid: int, 
    winner_bot_id: int,
    x_internal_secret: str = Header(..., alias="X-Internal-Secret"),
    db: Session = Depends(get_db),
):
    if x_internal_secret != INTERNAL_SECRET:
         raise HTTPException(status_code=403)
         
    system = TournamentBracket(db)
    system.record_result(tid, mid, winner_bot_id)
    return {"ok": True}

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "clawquake-orchestrator"}


# ── Docs Pages ───────────────────────────────────────────────────

@app.get("/docs-page")
def docs_page():
    if os.path.isdir(STATIC_DIR):
        path = os.path.join(STATIC_DIR, "docs.html")
        if os.path.exists(path):
            return FileResponse(path)
    raise HTTPException(status_code=404, detail="docs.html not found")


@app.get("/getting-started")
def getting_started_page():
    if os.path.isdir(STATIC_DIR):
        path = os.path.join(STATIC_DIR, "getting-started.html")
        if os.path.exists(path):
            return FileResponse(path)
    raise HTTPException(status_code=404, detail="getting-started.html not found")



# ── Replay Endpoints (Anti-Gravity — Batch 4) ───────────────────

REPLAY_DIR = os.environ.get("REPLAY_DIR", "replays")

@app.get("/api/replays")
def list_replays():
    if not os.path.isdir(REPLAY_DIR):
        return []
    files = []
    for f in os.listdir(REPLAY_DIR):
        if f.endswith(".json"):
            path = os.path.join(REPLAY_DIR, f)
            stat = os.stat(path)
            files.append({
                "filename": f,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime)
            })
    # Sort by recent
    files.sort(key=lambda x: x["modified"], reverse=True)
    return files

@app.get("/api/replays/{filename}")
def get_replay(filename: str):
    # Security check: no path traversal
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
        
    path = os.path.join(REPLAY_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Replay not found")
        
    return FileResponse(path)

# ── Static Files (must be last — catch-all) ─────────────────────

STATIC_DIR = os.environ.get("STATIC_DIR", "/app/static")
if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
