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
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user_or_apikey, get_db
from models import BotDB, UserDB, SessionLocal
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


def _validate_internal_secret(x_internal_secret: str):
    expected = os.environ.get("INTERNAL_SECRET", "")
    if not expected or x_internal_secret != expected:
        raise HTTPException(status_code=403, detail="Invalid internal secret")


def _observe_for_bot(bot_id: int) -> Dict[str, Any]:
    state = LATEST_STATES.get(bot_id)
    if not state:
        return {"status": "waiting_for_connection", "bot_id": bot_id}
    return state


@router.get("/observe")
def observe_get(
    bot_id: int = Query(...),
    user: UserDB = Depends(get_current_user_or_apikey),
    db: Session = Depends(get_db),
):
    _require_owned_bot(db, user, bot_id)
    return _observe_for_bot(bot_id)


@router.post("/observe")
def observe_post(
    bot_id: int = Query(...),
    user: UserDB = Depends(get_current_user_or_apikey),
    db: Session = Depends(get_db),
):
    _require_owned_bot(db, user, bot_id)
    return _observe_for_bot(bot_id)


@router.post("/act")
def act(
    action: ActionRequest,
    bot_id: int = Query(...),
    user: UserDB = Depends(get_current_user_or_apikey),
    db: Session = Depends(get_db),
):
    _require_owned_bot(db, user, bot_id)

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

def _auth_external_ws(db: Session, api_key: str, bot_id: int) -> Optional[BotDB]:
    """Authenticate an external agent WebSocket connection via API key."""
    from models import ApiKeyDB
    key_row = db.query(ApiKeyDB).filter(
        ApiKeyDB.key == api_key,
        ApiKeyDB.is_active == True,
    ).first()
    if not key_row:
        return None
    bot = db.query(BotDB).filter(BotDB.id == bot_id).first()
    if not bot or bot.owner_id != key_row.user_id:
        return None
    return bot


@router.websocket("/stream")
async def agent_stream(
    websocket: WebSocket,
    bot_id: int = Query(...),
    api_key: str = Query(""),
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
        bot = _auth_external_ws(db, api_key, bot_id)
    finally:
        db.close()

    if not bot:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    logger.info("External agent connected for bot %d", bot_id)

    # Send initial state snapshot
    initial = LATEST_STATES.get(bot_id)
    if initial:
        await websocket.send_json({"type": "state_snapshot", "state": initial})

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
