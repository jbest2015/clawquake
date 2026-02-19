"""
AI Agent Interface for interactive bot control.

External agents call:
  - observe: read latest bot state snapshot
  - act: queue an action for the bot

Agent runners call:
  - internal/sync: push latest state and receive pending actions
"""

import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user_or_apikey, get_db
from models import BotDB, UserDB

router = APIRouter(prefix="/api/agent", tags=["agent"])

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
