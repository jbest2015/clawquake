"""
AI Agent Interface for interactive bot control.

External agents call:
  - observe: read latest bot state snapshot (HTTP)
  - act: queue an action for the bot (HTTP)
  - ws /api/agent/stream: bidirectional telemetry + commands (WebSocket)

Agent runners call:
  - internal/sync: push latest state and receive pending actions (HTTP fallback)
  - ws /api/internal/telemetry: push telemetry, drain commands (WebSocket)
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agent_auth import (
    get_agent_registration_by_key,
    get_bot_by_user_api_key,
    mark_agent_registration_used,
)
from auth import _get_user_from_token, get_db, optional_security
from models import (
    BotDB, MatchDB, MatchParticipantDB, QueueEntryDB, SessionLocal,
    TournamentDB, TournamentMatchDB, TournamentParticipantDB, UserDB,
)
from telemetry_hub import TelemetryHub, validate_action

logger = logging.getLogger("clawquake.agent_interface")

router = APIRouter(prefix="/api/agent", tags=["agent"])

# TelemetryHub instance — set by main.py at startup
telemetry_hub: Optional[TelemetryHub] = None

HEARTBEAT_INTERVAL = 5.0  # seconds
HEARTBEAT_TIMEOUT = 10.0  # seconds
MAX_FRAME_SIZE = 65536  # 64KB max telemetry frame

# In-memory stores (single-orchestrator MVP)
# bot_id -> latest_state
LATEST_STATES: Dict[int, Dict[str, Any]] = {}
# bot_id -> queued action payloads
ACTION_QUEUES: Dict[int, List[Dict[str, Any]]] = {}

MAX_QUEUE_SIZE = 256

# ── Fog of War ────────────────────────────────────────────────────
# Perception range: 2D (XY) distance + Z band filter.
# Bots can only "hear" other bots on the same floor within a radius.
FOW_XY_RADIUS = 800     # horizontal hearing range in game units
FOW_Z_BAND = 128        # vertical band — ±128 units (roughly one floor)


def _is_perceivable(my_pos, other_pos):
    """Check if other_pos is within fog-of-war perception range of my_pos."""
    if not my_pos or not other_pos:
        return False
    dx = my_pos[0] - other_pos[0]
    dy = my_pos[1] - other_pos[1]
    xy_dist = (dx * dx + dy * dy) ** 0.5
    dz = abs(my_pos[2] - other_pos[2]) if len(my_pos) > 2 and len(other_pos) > 2 else 0
    return xy_dist < FOW_XY_RADIUS and dz < FOW_Z_BAND


class ActionRequest(BaseModel):
    action: str
    params: Dict[str, Any] = {}


class AgentState(BaseModel):
    tick: Optional[int] = None
    position: Optional[List[float]] = None
    health: Optional[int] = None
    armor: Optional[int] = None
    weapon: Optional[str] = None
    ammo: Dict[str, int] = {}
    visible_enemies: List[Dict[str, Any]] = []
    nearby_items: List[Dict[str, Any]] = []
    last_hit_by: Optional[str] = None
    score: Dict[str, int] = {}

    class Config:
        extra = "allow"


class RunnerUpdate(BaseModel):
    bot_id: int
    state: AgentState


def _require_owned_bot(db: Session, user: UserDB, bot_id: int) -> BotDB:
    bot = db.query(BotDB).filter(BotDB.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return bot


def _resolve_bot_access(
    db: Session,
    bot_id: int,
    credentials: Optional[HTTPAuthorizationCredentials],
    x_api_key: Optional[str],
    x_agent_key: Optional[str],
) -> BotDB:
    if x_agent_key:
        resolved = get_agent_registration_by_key(db, x_agent_key)
        if not resolved:
            raise HTTPException(status_code=401, detail="Invalid agent key")
        registration, bot = resolved
        if bot.id != bot_id:
            raise HTTPException(status_code=403, detail="Forbidden")
        mark_agent_registration_used(db, registration)
        return bot

    if credentials and credentials.scheme.lower() == "bearer":
        user = _get_user_from_token(credentials.credentials, db)
        return _require_owned_bot(db, user, bot_id)

    if x_api_key:
        bot = get_bot_by_user_api_key(db, x_api_key, bot_id)
        if bot:
            return bot
        raise HTTPException(status_code=401, detail="Invalid API key")

    raise HTTPException(status_code=401, detail="Authentication required")


def _validate_internal_secret(x_internal_secret: str):
    expected = os.environ.get("INTERNAL_SECRET", "")
    if not expected or x_internal_secret != expected:
        raise HTTPException(status_code=403, detail="Invalid internal secret")


def _observe_for_bot(bot_id: int) -> Dict[str, Any]:
    state = LATEST_STATES.get(bot_id)
    if not state:
        return {"status": "waiting_for_connection", "bot_id": bot_id}

    # Apply fog-of-war to the players list
    my_pos = state.get("my_position") or state.get("position")
    players = state.get("players")
    if my_pos and players:
        filtered = []
        for p in players:
            p_pos = p.get("position")
            if p_pos and _is_perceivable(my_pos, p_pos):
                filtered.append(p)
        # Return a copy with filtered players
        result = dict(state)
        result["players"] = filtered
        result["player_count"] = len(filtered)
        return result

    return state


@router.get("/observe")
def observe_get(
    bot_id: int = Query(...),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    x_agent_key: Optional[str] = Header(default=None, alias="X-Agent-Key"),
    db: Session = Depends(get_db),
):
    _resolve_bot_access(db, bot_id, credentials, x_api_key, x_agent_key)
    return _observe_for_bot(bot_id)


@router.post("/observe")
def observe_post(
    bot_id: int = Query(...),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    x_agent_key: Optional[str] = Header(default=None, alias="X-Agent-Key"),
    db: Session = Depends(get_db),
):
    _resolve_bot_access(db, bot_id, credentials, x_api_key, x_agent_key)
    return _observe_for_bot(bot_id)


@router.get("/bot-status")
def bot_status(
    bot_id: int = Query(...),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    x_agent_key: Optional[str] = Header(default=None, alias="X-Agent-Key"),
    db: Session = Depends(get_db),
):
    """Full situational awareness for an AI agent controlling a bot."""
    bot = _resolve_bot_access(db, bot_id, credentials, x_api_key, x_agent_key)

    result: Dict[str, Any] = {
        "bot_id": bot.id,
        "bot_name": bot.name,
        "strategy": bot.strategy or "default",
        "elo": bot.elo,
        "wins": bot.wins,
        "actions": {
            "ready": f"/api/agent/ready?bot_id={bot.id}",
            "observe": f"/api/agent/observe?bot_id={bot.id}",
            "act": f"/api/agent/act?bot_id={bot.id}",
            "bot_status": f"/api/agent/bot-status?bot_id={bot.id}",
            "strategies": "/api/strategies",
            "update_strategy": f"/api/bots/{bot.id}",
        },
        "losses": bot.losses,
        "kills": bot.kills,
        "deaths": bot.deaths,
        "tournament": None,
        "queue": None,
        "active_match": None,
    }

    # Check tournament participation
    tp = (
        db.query(TournamentParticipantDB)
        .filter(TournamentParticipantDB.bot_id == bot_id)
        .first()
    )
    if tp:
        tournament = db.query(TournamentDB).filter(TournamentDB.id == tp.tournament_id).first()
        if tournament and tournament.status in ("pending", "active"):
            t_count = db.query(TournamentParticipantDB).filter_by(tournament_id=tournament.id).count()
            # Find next opponent from bracket
            next_opponent = None
            if tournament.status == "active":
                tm = (
                    db.query(TournamentMatchDB)
                    .filter(
                        TournamentMatchDB.tournament_id == tournament.id,
                        TournamentMatchDB.winner_bot_id.is_(None),
                        (TournamentMatchDB.player1_bot_id == bot_id) | (TournamentMatchDB.player2_bot_id == bot_id),
                    )
                    .first()
                )
                if tm:
                    opp_id = tm.player2_bot_id if tm.player1_bot_id == bot_id else tm.player1_bot_id
                    if opp_id:
                        opp_bot = db.query(BotDB).filter(BotDB.id == opp_id).first()
                        next_opponent = opp_bot.name if opp_bot else None

            result["tournament"] = {
                "id": tournament.id,
                "name": tournament.name,
                "status": tournament.status,
                "my_seed": tp.seed,
                "eliminated": bool(tp.eliminated),
                "ready": bool(getattr(tp, "ready", 0)),
                "participants": t_count,
                "current_round": tournament.current_round,
                "next_opponent": next_opponent,
            }

    # Check queue status
    queue_entry = (
        db.query(QueueEntryDB)
        .filter(QueueEntryDB.bot_id == bot_id, QueueEntryDB.status.in_(["waiting", "matched"]))
        .order_by(QueueEntryDB.queued_at.desc())
        .first()
    )
    if queue_entry:
        position = (
            db.query(QueueEntryDB)
            .filter(QueueEntryDB.status == "waiting", QueueEntryDB.queued_at <= queue_entry.queued_at)
            .count()
        )
        result["queue"] = {
            "position": position,
            "status": queue_entry.status,
            "queued_at": queue_entry.queued_at.isoformat() if queue_entry.queued_at else None,
        }

    # Check active match
    active_participant = (
        db.query(MatchParticipantDB)
        .join(MatchDB, MatchDB.id == MatchParticipantDB.match_id)
        .filter(MatchParticipantDB.bot_id == bot_id, MatchDB.ended_at.is_(None))
        .first()
    )
    if active_participant:
        match = db.query(MatchDB).filter(MatchDB.id == active_participant.match_id).first()
        if match:
            opponents = []
            participants = db.query(MatchParticipantDB).filter(
                MatchParticipantDB.match_id == match.id,
                MatchParticipantDB.bot_id != bot_id,
            ).all()
            for p in participants:
                opp = db.query(BotDB).filter(BotDB.id == p.bot_id).first()
                if opp:
                    opponents.append(opp.name)

            result["active_match"] = {
                "match_id": match.id,
                "map_name": match.map_name,
                "opponents": opponents,
                "started_at": match.started_at.isoformat() if match.started_at else None,
            }

    return result


@router.post("/ready")
def mark_ready(
    bot_id: int = Query(...),
    ready: bool = Query(default=True),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    x_agent_key: Optional[str] = Header(default=None, alias="X-Agent-Key"),
    db: Session = Depends(get_db),
):
    """AI agent signals that its bot is ready (or not ready) for tournament play."""
    bot = _resolve_bot_access(db, bot_id, credentials, x_api_key, x_agent_key)

    # Find active tournament participation
    tp = (
        db.query(TournamentParticipantDB)
        .join(TournamentDB, TournamentDB.id == TournamentParticipantDB.tournament_id)
        .filter(
            TournamentParticipantDB.bot_id == bot_id,
            TournamentDB.status == "pending",
        )
        .first()
    )
    if not tp:
        raise HTTPException(status_code=404, detail="Bot is not in any pending tournament")

    tp.ready = 1 if ready else 0
    db.commit()

    tournament = db.query(TournamentDB).filter(TournamentDB.id == tp.tournament_id).first()
    return {
        "bot_id": bot.id,
        "bot_name": bot.name,
        "tournament_id": tp.tournament_id,
        "tournament_name": tournament.name if tournament else None,
        "ready": bool(tp.ready),
    }


@router.post("/act")
def act(
    action: ActionRequest,
    bot_id: int = Query(...),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    x_agent_key: Optional[str] = Header(default=None, alias="X-Agent-Key"),
    db: Session = Depends(get_db),
):
    _resolve_bot_access(db, bot_id, credentials, x_api_key, x_agent_key)

    action_name = action.action.strip()
    if not action_name:
        raise HTTPException(status_code=400, detail="Action is required")

    queue = ACTION_QUEUES.setdefault(bot_id, [])
    if len(queue) >= MAX_QUEUE_SIZE:
        raise HTTPException(status_code=429, detail="Action queue full")

    queue.append(
        {
            "action": action_name,
            "params": action.params or {},
            "queued_at": time.time(),
        }
    )
    return {"ok": True, "queued": True, "queue_length": len(queue)}


@router.get("/live-positions")
def live_positions(
    bot_id: Optional[int] = Query(default=None, description="Your bot ID for fog-of-war filtering"),
    db: Session = Depends(get_db),
):
    """Returns active bot positions. If bot_id is given, applies fog-of-war:
    only shows bots within perception range (800 XY units, ±128 Z)."""
    active_ids = list(LATEST_STATES.keys())
    bot_names = {}
    if active_ids:
        from models import BotDB
        for bot in db.query(BotDB).filter(BotDB.id.in_(active_ids)).all():
            bot_names[bot.id] = bot.name

    # Get requesting bot's position for fog-of-war filtering
    my_pos = None
    if bot_id is not None:
        my_state = LATEST_STATES.get(bot_id)
        if my_state:
            my_pos = my_state.get("my_position") or my_state.get("position")

    bots = []
    for bid, state in LATEST_STATES.items():
        pos = state.get("my_position") or state.get("position") or state.get("pos")
        if not pos or not isinstance(pos, (list, tuple)) or len(pos) < 2:
            continue

        # Always include the requesting bot's own position
        if bot_id is not None and bid != bot_id:
            if my_pos and not _is_perceivable(my_pos, pos):
                continue

        # Extract viewangles for firing direction
        angles = state.get("my_viewangles") or [0, 0, 0]
        yaw = angles[1] if len(angles) > 1 else 0

        # Detect firing from stats — ammo decrease or attack flag in last sync
        ammo = state.get("my_ammo") or []
        weapon = state.get("my_weapon") or "WP_MACHINEGUN"

        bots.append({
            "bot_id": bid,
            "name": bot_names.get(bid) or state.get("bot_name") or state.get("name") or f"Bot {bid}",
            "x": pos[0],
            "y": pos[1],
            "z": pos[2] if len(pos) > 2 else 0,
            "health": state.get("my_health") or state.get("health"),
            "yaw": yaw,
            "weapon": weapon,
            "ammo": ammo,
            "firing": state.get("player_count", 0) > 0,
        })
    # Aggregate discovered items from ALL bots (combined map reveal)
    seen_positions = set()
    items = []
    for bid, state in LATEST_STATES.items():
        for item in (state.get("nearby_items") or state.get("items") or []):
            pos = item.get("position")
            if not pos or not isinstance(pos, (list, tuple)) or len(pos) < 2:
                continue
            # Dedupe by rounded position (items at same spot from different bots)
            key = (round(pos[0]), round(pos[1]))
            if key in seen_positions:
                continue
            seen_positions.add(key)
            items.append({
                "x": pos[0],
                "y": pos[1],
                "z": pos[2] if len(pos) > 2 else 0,
                "type": item.get("type", "unknown"),
                "subtype": item.get("subtype", ""),
            })

    return {"bots": bots, "count": len(bots), "items": items}


@router.post("/internal/sync")
def sync_runner(
    update: RunnerUpdate,
    x_internal_secret: str = Header(..., alias="X-Internal-Secret"),
    db: Session = Depends(get_db),
):
    _validate_internal_secret(x_internal_secret)

    bot = db.query(BotDB).filter(BotDB.id == update.bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    LATEST_STATES[update.bot_id] = update.state.dict(exclude_none=True)

    actions = ACTION_QUEUES.get(update.bot_id, [])
    ACTION_QUEUES[update.bot_id] = []
    return {"actions": actions}


# ── WebSocket: External Agent Stream ─────────────────────────────

def _auth_external_ws(
    db: Session,
    bot_id: int,
    agent_key: str = "",
    api_key: str = "",
) -> Optional[BotDB]:
    """Authenticate an external agent WebSocket connection."""
    if agent_key:
        resolved = get_agent_registration_by_key(db, agent_key)
        if not resolved:
            return None
        registration, bot = resolved
        if bot.id != bot_id:
            return None
        mark_agent_registration_used(db, registration)
        return bot
    return get_bot_by_user_api_key(db, api_key, bot_id)


@router.websocket("/stream")
async def agent_stream(
    websocket: WebSocket,
    bot_id: int = Query(...),
    api_key: str = Query(""),
    agent_key: str = Query(""),
):
    """Bidirectional WebSocket for external AI agents.

    - Server → Client: telemetry frames at 20Hz (from TelemetryHub)
    - Client → Server: command frames {"type": "command", "actions": [...]}
    - Heartbeat: server pings every 5s, expects pong within 10s
    """
    if not telemetry_hub:
        await websocket.close(code=1013, reason="Telemetry not available")
        return

    # Auth
    db = SessionLocal()
    try:
        bot = _auth_external_ws(db, bot_id=bot_id, api_key=api_key, agent_key=agent_key)
    finally:
        db.close()

    if not bot:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    logger.info("External agent connected for bot %d", bot_id)

    # Send initial state snapshot (fog-of-war filtered)
    initial = LATEST_STATES.get(bot_id)
    if initial:
        await websocket.send_json({"type": "state_snapshot", "state": _observe_for_bot(bot_id)})

    # Subscribe to telemetry
    queue = await telemetry_hub.subscribe(bot_id)

    async def _send_telemetry():
        """Forward telemetry frames from hub to WebSocket client."""
        try:
            while True:
                frame = await queue.get()
                dropped = telemetry_hub.get_dropped_frames(queue)
                if dropped:
                    frame["dropped_frames"] = dropped
                await websocket.send_json(frame)
        except (WebSocketDisconnect, Exception):
            pass

    async def _receive_commands():
        """Receive command frames from WebSocket client."""
        try:
            while True:
                raw = await websocket.receive_text()
                if len(raw) > MAX_FRAME_SIZE:
                    await websocket.send_json({"type": "error", "message": "Frame too large"})
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                    continue

                if msg.get("type") == "command":
                    actions = msg.get("actions", [])
                    queue_list = ACTION_QUEUES.setdefault(bot_id, [])
                    for action_str in actions:
                        if not validate_action(action_str):
                            await websocket.send_json({
                                "type": "error",
                                "message": f"Invalid action: {action_str}",
                            })
                            continue
                        if len(queue_list) < MAX_QUEUE_SIZE:
                            queue_list.append({
                                "action": action_str,
                                "params": {},
                                "queued_at": time.time(),
                            })
        except (WebSocketDisconnect, Exception):
            pass

    async def _heartbeat():
        """Ping client periodically to detect stale connections."""
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await websocket.send_json({"type": "ping", "ts": time.time()})
        except (WebSocketDisconnect, Exception):
            pass

    try:
        await asyncio.gather(
            _send_telemetry(),
            _receive_commands(),
            _heartbeat(),
            return_exceptions=True,
        )
    finally:
        await telemetry_hub.unsubscribe(bot_id, queue)
        logger.info("External agent disconnected for bot %d", bot_id)


# ── WebSocket: Internal Bot Runner Telemetry ─────────────────────

@router.websocket("/internal/telemetry")
async def internal_telemetry(
    websocket: WebSocket,
    bot_id: int = Query(...),
    secret: str = Query(""),
):
    """WebSocket for bot runner → orchestrator telemetry.

    - Runner → Orchestrator: telemetry frames (20Hz)
    - Orchestrator → Runner: pending commands
    """
    expected_secret = os.environ.get("INTERNAL_SECRET", "")
    if not expected_secret or secret != expected_secret:
        await websocket.close(code=4001, reason="Invalid internal secret")
        return

    if not telemetry_hub:
        await websocket.close(code=1013, reason="Telemetry not available")
        return

    await websocket.accept()
    logger.info("Bot runner connected for bot %d", bot_id)

    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw) > MAX_FRAME_SIZE:
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Malformed JSON from runner bot %d", bot_id)
                continue

            msg_type = msg.get("type")

            if msg_type == "telemetry":
                # Store latest state
                state = msg.get("state", {})
                LATEST_STATES[bot_id] = state

                # Publish to subscribers
                await telemetry_hub.publish(bot_id, msg)

                # Return pending commands
                actions = ACTION_QUEUES.get(bot_id, [])
                ACTION_QUEUES[bot_id] = []
                await websocket.send_json({
                    "type": "commands",
                    "actions": actions,
                })

            elif msg_type == "event":
                # Forward events to telemetry subscribers
                await telemetry_hub.publish(bot_id, msg)

    except WebSocketDisconnect:
        logger.info("Bot runner disconnected for bot %d", bot_id)
    except Exception as e:
        logger.error("Error in internal telemetry for bot %d: %s", bot_id, e)
    finally:
        # Notify subscribers that bot disconnected
        await telemetry_hub.publish(bot_id, {
            "type": "disconnected",
            "bot_id": bot_id,
            "ts": time.time(),
        })
        logger.info("Bot runner cleanup complete for bot %d", bot_id)
