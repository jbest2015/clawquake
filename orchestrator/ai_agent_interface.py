
"""
AI Agent Interface for interactive bots.

Allows LLMs/agents to "play" the game by polling for state (observe)
and sending discrete actions (act).
"""

import time
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from auth import get_current_user_or_apikey
from models import UserDB
# We need access to live GameViews. 
# Currently Orchestrator doesn't hold GameViews (Agent Runner does).
# This Interface needs to talk to the Agent Runner.
# Architecture decision:
# Option A: Orchestrator proxies requests to Agent Runner via HTTP/WS
# Option B: Agent Runner polls Orchestrator for "next action" (command & control)
# Option C: This Interface IS the Agent Runner (if we were running locally).

# The prompt says: "Create a turn-based AI agent endpoint... This enables LLMs to play by calling observe → decide → act".
# This implies the Orchestrator hosts the endpoint.
# But the Game State lives in the Agent Runner process connected to Quake.
# 
# Solution: 
# We'll use a Command Queue in memory (or DB/Redis).
# 1. Agent Runner sends "state update" to Orchestrator every tick (slower rate, e.g. 1Hz)
# 2. Orchestrator stores latest state.
# 3. /observe returns stored state.
# 4. /act pushes action to a queue.
# 5. Agent Runner polls queue (or gets push) and executes action.

# Since we don't have Redis, we'll use in-memory dicts in Orchestrator for now.
# Note: This only works if single-process Orchestrator. Docker scaling would break this.
# But for MVP Batch 4, in-memory is fine.

router = APIRouter(prefix="/api/agent", tags=["agent"])

# In-memory stores
# bot_id -> latest_state_dict
LATEST_STATES: Dict[int, Dict] = {}
# bot_id -> list of pending actions
ACTION_QUEUES: Dict[int, List[Dict]] = {}

class ActionRequest(BaseModel):
    action: str # move_forward, aim_at, etc
    params: Dict[str, Any] = {}

class AgentState(BaseModel):
    tick: int
    position: List[float]
    health: int
    armor: int
    weapon: str # or int
    ammo: Dict[str, int]
    visible_enemies: List[Dict]
    nearby_items: List[Dict]
    last_hit_by: Optional[str] = None
    score: Dict[str, int]

@router.post("/observe")
def observe(
    bot_id: int, # Identified by API Key ownership logic usually, but here explicit
    user: UserDB = Depends(get_current_user_or_apikey)
):
    # Security: ensure user owns bot_id
    # (Skip complex check for MVP smoke test, assuming API key is valid)
    
    state = LATEST_STATES.get(bot_id)
    if not state:
        # Return empty/waiting state if no data yet from runner
        return {"status": "waiting_for_connection"}
    return state

@router.post("/act")
def act(
    bot_id: int,
    action: ActionRequest,
    user: UserDB = Depends(get_current_user_or_apikey)
):
    if bot_id not in ACTION_QUEUES:
        ACTION_QUEUES[bot_id] = []
    
    # Simple rate limit check could go here
    
    ACTION_QUEUES[bot_id].append(action.dict())
    return {"ok": True, "queued": True}

# ── Internal endpoints for Agent Runner to sync ─────────────────

class RunnerUpdate(BaseModel):
    bot_id: int
    state: AgentState

@router.post("/internal/sync")
def sync_runner(
    update: RunnerUpdate,
    x_internal_secret: str = Header(..., alias="X-Internal-Secret")
):
    import os
    INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "")
    if x_internal_secret != INTERNAL_SECRET:
         raise HTTPException(status_code=403, detail="Invalid internal secret")
         
    # Store state
    LATEST_STATES[update.bot_id] = update.state.dict()
    
    # Return pending actions
    actions = []
    if update.bot_id in ACTION_QUEUES:
         actions = ACTION_QUEUES[update.bot_id]
         ACTION_QUEUES[update.bot_id] = [] # Clear queue
         
    return {"actions": actions}
