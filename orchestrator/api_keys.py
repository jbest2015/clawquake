"""
API key helpers for bot and queue authentication.
"""

import hashlib
import hmac
import secrets
from typing import Optional

from sqlalchemy.orm import Session

from models import ApiKeyDB, UserDB

API_KEY_PREFIX = "cq_"


def generate_api_key() -> str:
    """Generate a new user-facing API key."""
    token = secrets.token_hex(20)
    return f"{API_KEY_PREFIX}{token}"


def hash_api_key(api_key: str) -> str:
    """Return a stable hash for DB storage."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def verify_api_key(api_key: str, api_key_hash: str) -> bool:
    """Constant-time API key verification."""
    candidate = hash_api_key(api_key)
    return hmac.compare_digest(candidate, api_key_hash)


def get_user_by_api_key(api_key: str, db: Session) -> Optional[UserDB]:
    """Resolve and validate an active API key to its owning user."""
    key_hash = hash_api_key(api_key)
    key = (
        db.query(ApiKeyDB)
        .filter(ApiKeyDB.key_hash == key_hash, ApiKeyDB.is_active == 1)
        .first()
    )
    if not key:
        return None
    return db.query(UserDB).filter(UserDB.id == key.user_id).first()
