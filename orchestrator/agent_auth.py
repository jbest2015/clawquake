"""
Helpers for bot-scoped agent registration authentication.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from api_keys import hash_api_key
from models import AgentRegistrationDB, ApiKeyDB, BotDB


def get_agent_registration_by_key(
    db: Session,
    raw_key: str,
) -> Optional[tuple[AgentRegistrationDB, BotDB]]:
    if not raw_key:
        return None

    key_hash = hash_api_key(raw_key)
    registration = (
        db.query(AgentRegistrationDB)
        .filter(
            AgentRegistrationDB.key_hash == key_hash,
            AgentRegistrationDB.status == "active",
        )
        .first()
    )
    if not registration:
        return None

    if registration.expires_at and registration.expires_at <= datetime.utcnow():
        return None

    bot = db.query(BotDB).filter(BotDB.id == registration.bot_id).first()
    if not bot:
        return None

    return registration, bot


def mark_agent_registration_used(db: Session, registration: AgentRegistrationDB):
    now = datetime.utcnow()
    if registration.claimed_at is None:
        registration.claimed_at = now
    registration.last_used = now
    db.commit()


def get_bot_by_user_api_key(
    db: Session,
    raw_key: str,
    bot_id: int,
) -> Optional[BotDB]:
    if not raw_key:
        return None

    key_hash = hash_api_key(raw_key)
    key = (
        db.query(ApiKeyDB)
        .filter(ApiKeyDB.key_hash == key_hash, ApiKeyDB.is_active == 1)
        .first()
    )
    if not key:
        return None

    if key.expires_at and key.expires_at <= datetime.utcnow():
        return None

    bot = db.query(BotDB).filter(BotDB.id == bot_id).first()
    if not bot or bot.owner_id != key.user_id:
        return None

    key.last_used = datetime.utcnow()
    db.commit()
    return bot
