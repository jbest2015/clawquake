from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api_keys import generate_api_key, hash_api_key
from auth import get_current_user, get_db
from models import ApiKeyCreate, ApiKeyCreated, ApiKeyDB, ApiKeyResponse, UserDB

router = APIRouter(tags=["keys"])


@router.post("/api/keys", response_model=ApiKeyCreated)
def create_api_key(
    payload: ApiKeyCreate,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    name = payload.name.strip() or "default"
    raw_key = generate_api_key()

    expires_at = None
    if payload.expires_in_days is not None and payload.expires_in_days > 0:
        expires_at = datetime.utcnow() + timedelta(days=payload.expires_in_days)

    key = ApiKeyDB(
        user_id=user.id,
        name=name,
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        expires_at=expires_at,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return ApiKeyCreated(
        id=key.id,
        name=key.name,
        key=raw_key,
        key_prefix=key.key_prefix,
        created_at=key.created_at,
    )


@router.get("/api/keys", response_model=list[ApiKeyResponse])
def list_api_keys(
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    keys = (
        db.query(ApiKeyDB)
        .filter(ApiKeyDB.user_id == user.id, ApiKeyDB.is_active == 1)
        .order_by(ApiKeyDB.created_at.desc())
        .all()
    )
    return [
        ApiKeyResponse(
            id=key.id,
            name=key.name,
            key_prefix=key.key_prefix,
            created_at=key.created_at,
            last_used=key.last_used,
            is_active=bool(key.is_active),
            expires_at=getattr(key, "expires_at", None),
        )
        for key in keys
    ]


@router.delete("/api/keys/{key_id}")
def delete_api_key(
    key_id: int,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    key = (
        db.query(ApiKeyDB)
        .filter(ApiKeyDB.id == key_id, ApiKeyDB.user_id == user.id)
        .first()
    )
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    key.is_active = 0
    key.last_used = datetime.utcnow()
    db.commit()
    return {"deleted": True}


@router.delete("/api/keys")
def delete_api_key_query(
    key_id: int = Query(...),
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return delete_api_key(key_id=key_id, user=user, db=db)


@router.post("/api/keys/{key_id}/rotate", response_model=ApiKeyCreated)
def rotate_api_key(
    key_id: int,
    user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Rotate an API key: revoke the old key and issue a new one
    with the same name and expiry window.

    Returns the new key (shown once). The old key is immediately invalidated.
    """
    old_key = (
        db.query(ApiKeyDB)
        .filter(
            ApiKeyDB.id == key_id,
            ApiKeyDB.user_id == user.id,
            ApiKeyDB.is_active == 1,
        )
        .first()
    )
    if not old_key:
        raise HTTPException(status_code=404, detail="API key not found or already revoked")

    # Calculate remaining expiry if the old key had one
    new_expires_at = None
    if old_key.expires_at:
        remaining = old_key.expires_at - datetime.utcnow()
        if remaining.total_seconds() <= 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot rotate an expired key. Create a new key instead.",
            )
        new_expires_at = datetime.utcnow() + remaining

    # Revoke old key
    old_key.is_active = 0
    old_key.last_used = datetime.utcnow()

    # Create new key with same name
    raw_key = generate_api_key()
    new_key = ApiKeyDB(
        user_id=user.id,
        name=old_key.name,
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        expires_at=new_expires_at,
    )
    db.add(new_key)
    db.commit()
    db.refresh(new_key)

    return ApiKeyCreated(
        id=new_key.id,
        name=new_key.name,
        key=raw_key,
        key_prefix=new_key.key_prefix,
        created_at=new_key.created_at,
    )
