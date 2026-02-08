from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth import get_current_user_or_apikey, get_db
from models import BotDB, QueueEntryDB, QueueJoin, QueueStatus, UserDB

router = APIRouter(tags=["queue"])

ACTIVE_QUEUE_STATUSES = ("waiting", "matched", "playing")


def _get_owned_bot(db: Session, user_id: int, bot_id: int) -> BotDB:
    bot = db.query(BotDB).filter(BotDB.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    if bot.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return bot


@router.post("/api/queue/join", response_model=QueueStatus)
def join_queue(
    payload: QueueJoin,
    user: UserDB = Depends(get_current_user_or_apikey),
    db: Session = Depends(get_db),
):
    bot = _get_owned_bot(db, user.id, payload.bot_id)

    existing = (
        db.query(QueueEntryDB)
        .filter(
            QueueEntryDB.bot_id == bot.id,
            QueueEntryDB.status.in_(ACTIVE_QUEUE_STATUSES),
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Bot is already in queue")

    entry = QueueEntryDB(bot_id=bot.id, user_id=user.id, status="waiting")
    db.add(entry)
    db.commit()
    db.refresh(entry)

    waiting_entries = (
        db.query(QueueEntryDB)
        .filter(QueueEntryDB.status == "waiting")
        .order_by(QueueEntryDB.queued_at.asc())
        .all()
    )
    waiting_ids = [e.id for e in waiting_entries]
    position = waiting_ids.index(entry.id) + 1 if entry.id in waiting_ids else 0

    return QueueStatus(
        position=position,
        bot_name=bot.name,
        status=entry.status,
        queued_at=entry.queued_at,
    )


@router.get("/api/queue/status", response_model=QueueStatus)
def queue_status(
    bot_id: int | None = Query(default=None),
    user: UserDB = Depends(get_current_user_or_apikey),
    db: Session = Depends(get_db),
):
    if bot_id is not None:
        bot = _get_owned_bot(db, user.id, bot_id)
    else:
        bot = (
            db.query(BotDB)
            .filter(BotDB.owner_id == user.id)
            .order_by(BotDB.created_at.asc())
            .first()
        )
        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")

    entry = (
        db.query(QueueEntryDB)
        .filter(
            QueueEntryDB.bot_id == bot.id,
            QueueEntryDB.status.in_(ACTIVE_QUEUE_STATUSES),
        )
        .order_by(QueueEntryDB.queued_at.asc())
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Bot is not currently queued")

    waiting_entries = (
        db.query(QueueEntryDB)
        .filter(QueueEntryDB.status == "waiting")
        .order_by(QueueEntryDB.queued_at.asc())
        .all()
    )
    waiting_ids = [e.id for e in waiting_entries]
    position = (waiting_ids.index(entry.id) + 1) if entry.status == "waiting" and entry.id in waiting_ids else 0

    return QueueStatus(
        position=position,
        bot_name=bot.name,
        status=entry.status,
        queued_at=entry.queued_at,
    )


@router.delete("/api/queue/leave")
def leave_queue(
    bot_id: int | None = Query(default=None),
    user: UserDB = Depends(get_current_user_or_apikey),
    db: Session = Depends(get_db),
):
    if bot_id is not None:
        bot = _get_owned_bot(db, user.id, bot_id)
    else:
        bot = (
            db.query(BotDB)
            .filter(BotDB.owner_id == user.id)
            .order_by(BotDB.created_at.asc())
            .first()
        )
        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")
    entry = (
        db.query(QueueEntryDB)
        .filter(
            QueueEntryDB.bot_id == bot.id,
            QueueEntryDB.status.in_(ACTIVE_QUEUE_STATUSES),
        )
        .order_by(QueueEntryDB.queued_at.desc())
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Bot is not currently queued")

    db.delete(entry)
    db.commit()
    return {"left": True}
