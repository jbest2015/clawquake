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
from typing import Optional

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
from routes_agents import router as agents_router
from routes_keys import router as keys_router
from routes_queue import router as queue_router
from rcon import get_server_status, add_bot, change_map, server_say, send_rcon
from rcon_pool import RconPool
from process_manager import BotProcessManager
from matchmaker import MatchMaker
from websocket_hub import WebSocketHub
from tournament.bracket import TournamentBracket
from models import (
    TournamentCreate, TournamentJoin, TournamentResponse, TournamentDB, TournamentParticipantDB
)
from models import TournamentMatchDB
from ai_agent_interface import router as ai_agent_router
import ai_agent_interface
from telemetry_hub import TelemetryHub

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
telemetry_hub = TelemetryHub()
ai_agent_interface.telemetry_hub = telemetry_hub
event_queue: SimpleQueue[tuple[str, dict]] = SimpleQueue()
websocket_publisher_task: asyncio.Task | None = None
tournament_tasks: dict[int, asyncio.Task] = {}


app = FastAPI(title="ClawQuake Orchestrator", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bots_router)
app.include_router(agents_router)
app.include_router(keys_router)
app.include_router(queue_router)
app.include_router(ai_agent_router)


def _status_payload() -> dict:
    """Current server status payload used by HTTP and WebSocket paths."""
    data = get_server_status()
    if not data["online"]:
        # QuakeJS websocket servers may not answer UDP getstatus probes.
        # If bot processes are actively running a match, treat status as live.
        active = [
            m for m in process_manager.active_matches()
            if not m.get("all_finished")
        ]
        if active:
            current = active[0]
            return {
                "online": True,
                "map_name": "q3dm17",
                "hostname": "ClawQuake Arena",
                "gametype": "ffa",
                "fraglimit": "50",
                "timelimit": str(max(1, int(current.get("duration", 120)) // 60)),
                "players": [],
                "player_count": 0,
                "max_clients": "16",
                "message": "Live match in progress",
            }
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
            await websocket_hub.broadcast(
                "match_started",
                {"match_id": match_id, "spectate_path": "/play/"},
            )
        for match_id in ended:
            await websocket_hub.broadcast("match_ended", {"match_id": match_id})
        previous_active = active_ids

        await asyncio.sleep(3.0)


matchmaker_task: asyncio.Task | None = None


@app.on_event("startup")
async def _migrate_tournament_columns():
    """Add new tournament columns if missing (SQLite ALTER TABLE)."""
    db = SessionLocal()
    try:
        from sqlalchemy import text
        cols = {row[1] for row in db.execute(text("PRAGMA table_info(tournaments)")).fetchall()}
        if "description" not in cols:
            db.execute(text("ALTER TABLE tournaments ADD COLUMN description TEXT DEFAULT ''"))
        if "max_participants" not in cols:
            db.execute(text("ALTER TABLE tournaments ADD COLUMN max_participants INTEGER DEFAULT 16"))
        db.commit()
    except Exception:
        pass
    finally:
        db.close()


@app.on_event("startup")
async def _startup_matchmaker():
    global matchmaker_task
    if matchmaker_task is None or matchmaker_task.done():
        matchmaker_task = asyncio.create_task(matchmaker.run_loop())


@app.on_event("startup")
async def _startup_websocket_publisher():
    global websocket_publisher_task
    if websocket_publisher_task is None or websocket_publisher_task.done():
        websocket_publisher_task = asyncio.create_task(_websocket_publish_loop())


@app.on_event("shutdown")
async def _shutdown_matchmaker():
    global matchmaker_task
    matchmaker._running = False
    if matchmaker_task:
        matchmaker_task.cancel()
        with suppress(asyncio.CancelledError):
            await matchmaker_task
        matchmaker_task = None


@app.on_event("shutdown")
async def _shutdown_tournaments():
    for task in list(tournament_tasks.values()):
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    tournament_tasks.clear()


def _bot_name_map(db: Session) -> dict[int, str]:
    return {
        bot.id: bot.name
        for bot in db.query(BotDB).all()
    }


async def _run_tournament(tournament_id: int):
    try:
        while True:
            db = SessionLocal()
            ready_match = None
            try:
                tournament = db.query(TournamentDB).filter(TournamentDB.id == tournament_id).first()
                if not tournament or tournament.status != "active":
                    return

                system = TournamentBracket(db)
                ready = system.get_ready_matches(tournament_id)
                if ready:
                    ready_match = ready[0]
                    bot_ids = [ready_match.player1_bot_id, ready_match.player2_bot_id]
                    game_match_id = matchmaker.create_direct_match(db, bot_ids)
                    ready_match.game_match_id = game_match_id
                    db.commit()
                else:
                    unfinished = (
                        db.query(TournamentMatchDB)
                        .filter(
                            TournamentMatchDB.tournament_id == tournament_id,
                            TournamentMatchDB.winner_bot_id.is_(None),
                        )
                        .count()
                    )
                    if unfinished == 0 and tournament.status == "completed":
                        return
            finally:
                db.close()

            if not ready_match:
                await asyncio.sleep(1.0)
                continue

            result = await matchmaker.run_existing_match(
                ready_match.game_match_id,
                [ready_match.player1_bot_id, ready_match.player2_bot_id],
            )

            if not result or not result.get("winner_id"):
                await asyncio.sleep(1.0)
                continue

            db = SessionLocal()
            try:
                system = TournamentBracket(db)
                system.record_result(
                    tournament_id,
                    ready_match.id,
                    int(result["winner_id"]),
                )
            finally:
                db.close()
    finally:
        tournament_tasks.pop(tournament_id, None)


def _ensure_tournament_runner(tournament_id: int):
    existing = tournament_tasks.get(tournament_id)
    if existing and not existing.done():
        return
    tournament_tasks[tournament_id] = asyncio.create_task(_run_tournament(tournament_id))


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


DASHBOARD_TELEMETRY_HZ = 5
DASHBOARD_TELEMETRY_INTERVAL = 1.0 / DASHBOARD_TELEMETRY_HZ  # 200ms


@app.websocket("/ws/bot-telemetry/{bot_id}")
async def websocket_bot_telemetry(ws: WebSocket, bot_id: int):
    """Rate-limited (5Hz) telemetry stream for dashboard spectators.

    Subscribes to TelemetryHub for the given bot_id and forwards frames
    at most 5 times per second. Intermediate frames are dropped — only
    the latest is sent each interval.
    """
    await ws.accept()

    # Send initial state snapshot if available
    from ai_agent_interface import LATEST_STATES
    initial = LATEST_STATES.get(bot_id)
    if initial:
        await ws.send_json({"type": "state_snapshot", "bot_id": bot_id, "state": initial})

    queue = await telemetry_hub.subscribe(bot_id)

    async def _rate_limited_send():
        """Drain hub queue at 5Hz, forwarding only the latest frame."""
        try:
            while True:
                await asyncio.sleep(DASHBOARD_TELEMETRY_INTERVAL)
                # Drain queue — keep only the latest frame
                latest = None
                while not queue.empty():
                    try:
                        latest = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                if latest is not None:
                    dropped = telemetry_hub.get_dropped_frames(queue)
                    if dropped:
                        latest["dropped_frames"] = dropped
                    await ws.send_json(latest)
        except (WebSocketDisconnect, Exception):
            pass

    async def _receive_keepalive():
        """Accept pings from the dashboard client."""
        try:
            while True:
                msg = await ws.receive_text()
                if msg.lower() == "ping":
                    await ws.send_json({"type": "pong"})
        except (WebSocketDisconnect, Exception):
            pass

    try:
        await asyncio.gather(
            _rate_limited_send(),
            _receive_keepalive(),
            return_exceptions=True,
        )
    finally:
        await telemetry_hub.unsubscribe(bot_id, queue)


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
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    system = TournamentBracket(db)
    bracket = system.create_tournament(t.name, t.format, created_by_user_id=user.id)
    # Set extra fields not handled by bracket engine
    bracket.description = t.description
    bracket.max_participants = t.max_participants
    db.commit()
    db.refresh(bracket)
    return TournamentResponse(
        id=bracket.id, name=bracket.name, description=bracket.description or "",
        format=bracket.format, max_participants=bracket.max_participants or 16,
        created_by_user_id=bracket.created_by_user_id, creator_name=user.username,
        status="pending", participant_count=0, current_round=0,
        winner_bot_id=None, created_at=bracket.created_at,
    )


@app.get("/api/tournaments", response_model=list[TournamentResponse])
def list_tournaments(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(TournamentDB).order_by(TournamentDB.created_at.desc())
    if status:
        query = query.filter(TournamentDB.status == status)
    tournaments = query.limit(100).all()

    # Batch-load creator names and winner names
    user_ids = {t.created_by_user_id for t in tournaments if t.created_by_user_id}
    user_map = {u.id: u.username for u in db.query(UserDB).filter(UserDB.id.in_(user_ids)).all()} if user_ids else {}
    bot_name_map = _bot_name_map(db)

    items: list[TournamentResponse] = []
    for tournament in tournaments:
        participant_count = (
            db.query(TournamentParticipantDB)
            .filter(TournamentParticipantDB.tournament_id == tournament.id)
            .count()
        )
        items.append(
            TournamentResponse(
                id=tournament.id,
                name=tournament.name,
                description=getattr(tournament, "description", "") or "",
                format=tournament.format,
                max_participants=getattr(tournament, "max_participants", 16) or 16,
                created_by_user_id=tournament.created_by_user_id,
                creator_name=user_map.get(tournament.created_by_user_id),
                status=tournament.status,
                participant_count=participant_count,
                current_round=tournament.current_round,
                winner_bot_id=tournament.winner_bot_id,
                winner_name=bot_name_map.get(tournament.winner_bot_id),
                created_at=tournament.created_at,
            )
        )
    return items

@app.post("/api/tournaments/{tid}/join")
def join_tournament(
    tid: int,
    join: TournamentJoin,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    system = TournamentBracket(db)
    tournament = db.query(TournamentDB).filter_by(id=tid).first()
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if tournament.status != "pending":
        raise HTTPException(status_code=400, detail="Tournament is not accepting new bots")

    # Enforce max participants
    max_p = getattr(tournament, "max_participants", 16) or 16
    current_count = db.query(TournamentParticipantDB).filter_by(tournament_id=tid).count()
    if current_count >= max_p:
        raise HTTPException(status_code=400, detail=f"Tournament is full ({max_p} bots max)")

    bot = db.query(BotDB).filter_by(id=join.bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Not your bot")

    success = system.add_participant(tid, join.bot_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to join (already present or tournament active)")
    return {"joined": True, "bot": bot.name, "participants": current_count + 1, "max": max_p}


@app.delete("/api/tournaments/{tid}/leave")
def leave_tournament(
    tid: int,
    bot_id: int,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tournament = db.query(TournamentDB).filter_by(id=tid).first()
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if tournament.status != "pending":
        raise HTTPException(status_code=400, detail="Cannot leave after tournament has started")

    bot = db.query(BotDB).filter_by(id=bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    if bot.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Not your bot")

    participant = (
        db.query(TournamentParticipantDB)
        .filter_by(tournament_id=tid, bot_id=bot_id)
        .first()
    )
    if not participant:
        raise HTTPException(status_code=404, detail="Bot not in this tournament")

    db.delete(participant)
    db.commit()
    return {"left": True, "bot": bot.name}

@app.post("/api/tournaments/{tid}/start")
async def start_tournament(
    tid: int,
    user: UserDB = Depends(get_current_user), # Admin only? Or owner?
    db: Session = Depends(get_db),
):
    tournament = db.query(TournamentDB).filter(TournamentDB.id == tid).first()
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if not user.is_admin and tournament.created_by_user_id != user.id:
        raise HTTPException(status_code=403, detail="Tournament owner or admin required")

    system = TournamentBracket(db)
    ok = system.start_tournament(tid)
    if not ok:
        raise HTTPException(status_code=400, detail="Could not start (not enough players or already started)")
    _ensure_tournament_runner(tid)
    return {"started": True}

@app.get("/api/tournaments/{tid}")
def get_tournament(
    tid: int,
    db: Session = Depends(get_db),
):
    system = TournamentBracket(db)
    # Get tournament info
    t = db.query(TournamentDB).get(tid)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
        
    count = db.query(TournamentParticipantDB).filter_by(tournament_id=tid).count()
    bracket_data = system.get_bracket(tid)
    bot_names = _bot_name_map(db)
    participants = (
        db.query(TournamentParticipantDB)
        .filter_by(tournament_id=tid)
        .order_by(TournamentParticipantDB.seed.asc(), TournamentParticipantDB.id.asc())
        .all()
    )
    
    # Format matches for JSON
    rounds_json = {}
    for r_num, matches in bracket_data.items():
        m_list = []
        for m in matches:
            m_list.append({
                "match_id": m.id,
                "match_num": m.match_num,
                "p1": m.player1_bot_id,
                "p1_name": bot_names.get(m.player1_bot_id, "TBD") if m.player1_bot_id else "TBD",
                "p2": m.player2_bot_id,
                "p2_name": bot_names.get(m.player2_bot_id, "TBD") if m.player2_bot_id else "TBD",
                "winner": m.winner_bot_id,
                "winner_name": bot_names.get(m.winner_bot_id) if m.winner_bot_id else None,
                "next": m.next_match_id,
                "game_match_id": m.game_match_id,
            })
        rounds_json[r_num] = m_list
        
    # Get creator name
    creator = db.query(UserDB).filter(UserDB.id == t.created_by_user_id).first() if t.created_by_user_id else None

    # Get bot details (ELO, owner) for participants
    bot_ids = [p.bot_id for p in participants]
    bots_detail = {b.id: b for b in db.query(BotDB).filter(BotDB.id.in_(bot_ids)).all()} if bot_ids else {}
    owner_ids = {b.owner_id for b in bots_detail.values()}
    owner_map = {u.id: u.username for u in db.query(UserDB).filter(UserDB.id.in_(owner_ids)).all()} if owner_ids else {}

    return {
        "info": TournamentResponse(
             id=t.id, name=t.name, description=getattr(t, "description", "") or "",
             format=t.format, max_participants=getattr(t, "max_participants", 16) or 16,
             status=t.status, created_by_user_id=t.created_by_user_id,
             creator_name=creator.username if creator else None,
             participant_count=count, current_round=t.current_round,
             winner_bot_id=t.winner_bot_id,
             winner_name=bot_names.get(t.winner_bot_id),
             created_at=t.created_at,
        ),
        "participants": [
            {
                "bot_id": participant.bot_id,
                "bot_name": bot_names.get(participant.bot_id, f"Bot {participant.bot_id}"),
                "owner": owner_map.get(bots_detail[participant.bot_id].owner_id) if participant.bot_id in bots_detail else None,
                "elo": bots_detail[participant.bot_id].elo if participant.bot_id in bots_detail else None,
                "strategy": bots_detail[participant.bot_id].strategy if participant.bot_id in bots_detail else None,
                "seed": participant.seed,
                "eliminated": bool(participant.eliminated),
            }
            for participant in participants
        ],
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
