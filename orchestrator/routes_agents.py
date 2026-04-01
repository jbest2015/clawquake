from datetime import datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from agent_auth import get_agent_registration_by_key, mark_agent_registration_used
from api_keys import generate_api_key, hash_api_key
from auth import get_current_user, get_db
from models import (
    AgentRegistrationCreate,
    AgentRegistrationCreated,
    AgentRegistrationDB,
    AgentRegistrationResponse,
    BotDB,
    UserDB,
)

router = APIRouter(tags=["agents"])


def _get_owned_bot(db: Session, user_id: int, bot_id: int) -> BotDB:
    bot = db.query(BotDB).filter(BotDB.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    if bot.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return bot


def _registration_response(registration: AgentRegistrationDB) -> AgentRegistrationResponse:
    return AgentRegistrationResponse(
        id=registration.id,
        bot_id=registration.bot_id,
        created_by_user_id=registration.created_by_user_id,
        name=registration.name,
        key_prefix=registration.key_prefix,
        status=registration.status,
        created_at=registration.created_at,
        claimed_at=registration.claimed_at,
        last_used=registration.last_used,
        expires_at=registration.expires_at,
    )


@router.post(
    "/api/bots/{bot_id}/agent-registrations",
    response_model=AgentRegistrationCreated,
)
def create_agent_registration(
    bot_id: int,
    payload: AgentRegistrationCreate,
    request: Request,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bot = _get_owned_bot(db, user.id, bot_id)

    raw_key = generate_api_key()
    expires_at = None
    if payload.expires_in_days is not None and payload.expires_in_days > 0:
        expires_at = datetime.utcnow() + timedelta(days=payload.expires_in_days)

    registration = AgentRegistrationDB(
        bot_id=bot.id,
        created_by_user_id=user.id,
        name=payload.name.strip() or "primary",
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        expires_at=expires_at,
    )
    db.add(registration)
    db.commit()
    db.refresh(registration)

    base_url = str(request.base_url).rstrip("/")
    invite_url = f"{base_url}/getting-started?{urlencode({'agent_key': raw_key})}"

    return AgentRegistrationCreated(
        **_registration_response(registration).model_dump(),
        invite_url=invite_url,
        agent_key=raw_key,
    )


@router.get(
    "/api/bots/{bot_id}/agent-registrations",
    response_model=list[AgentRegistrationResponse],
)
def list_agent_registrations(
    bot_id: int,
    include_revoked: bool = Query(default=False),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_bot(db, user.id, bot_id)
    query = db.query(AgentRegistrationDB).filter(AgentRegistrationDB.bot_id == bot_id)
    if not include_revoked:
        query = query.filter(AgentRegistrationDB.status == "active")
    registrations = query.order_by(AgentRegistrationDB.created_at.desc()).all()
    return [_registration_response(registration) for registration in registrations]


@router.delete("/api/agent-registrations/{registration_id}")
def revoke_agent_registration(
    registration_id: int,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    registration = (
        db.query(AgentRegistrationDB)
        .filter(AgentRegistrationDB.id == registration_id)
        .first()
    )
    if not registration:
        raise HTTPException(status_code=404, detail="Agent registration not found")

    bot = _get_owned_bot(db, user.id, registration.bot_id)
    registration.status = "revoked"
    registration.last_used = datetime.utcnow()
    db.commit()
    return {"revoked": True, "bot_id": bot.id}


@router.get("/api/agent/connect")
def connect_agent(
    request: Request,
    agent_key: str = Query(...),
    db: Session = Depends(get_db),
):
    resolved = get_agent_registration_by_key(db, agent_key)
    if not resolved:
        raise HTTPException(status_code=404, detail="Agent link not found or expired")

    registration, bot = resolved
    mark_agent_registration_used(db, registration)
    base_url = str(request.base_url).rstrip("/")

    return {
        "bot_id": bot.id,
        "bot_name": bot.name,
        "strategy": bot.strategy or "default",
        "registration_id": registration.id,
        "claimed": registration.claimed_at is not None,
        "observe_url": f"{base_url}/api/agent/observe?bot_id={bot.id}",
        "act_url": f"{base_url}/api/agent/act?bot_id={bot.id}",
        "stream_url": f"{base_url.replace('http://', 'ws://').replace('https://', 'wss://')}/api/agent/stream?bot_id={bot.id}&agent_key={agent_key}",
    }
