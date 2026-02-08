from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_db, get_current_user_or_apikey
from models import BotDB, BotRegister, BotResponse, UserDB

router = APIRouter(tags=["bots"])


@router.post("/api/bots", response_model=BotResponse)
def register_bot(
    payload: BotRegister,
    user: UserDB = Depends(get_current_user_or_apikey),
    db: Session = Depends(get_db),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Bot name is required")

    if db.query(BotDB).filter(BotDB.name == name).first():
        raise HTTPException(status_code=400, detail="Bot name already taken")

    bot = BotDB(name=name, owner_id=user.id)
    db.add(bot)
    db.commit()
    db.refresh(bot)

    return BotResponse(
        id=bot.id,
        name=bot.name,
        elo=bot.elo,
        wins=bot.wins,
        losses=bot.losses,
        kills=bot.kills,
        deaths=bot.deaths,
    )


@router.get("/api/bots", response_model=list[BotResponse])
def list_bots(
    user: UserDB = Depends(get_current_user_or_apikey),
    db: Session = Depends(get_db),
):
    bots = (
        db.query(BotDB)
        .filter(BotDB.owner_id == user.id)
        .order_by(BotDB.created_at.desc())
        .all()
    )
    return [
        BotResponse(
            id=bot.id,
            name=bot.name,
            elo=bot.elo,
            wins=bot.wins,
            losses=bot.losses,
            kills=bot.kills,
            deaths=bot.deaths,
        )
        for bot in bots
    ]


@router.get("/api/bots/{bot_id}", response_model=BotResponse)
def bot_details(
    bot_id: int,
    user: UserDB = Depends(get_current_user_or_apikey),
    db: Session = Depends(get_db),
):
    bot = db.query(BotDB).filter(BotDB.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    return BotResponse(
        id=bot.id,
        name=bot.name,
        elo=bot.elo,
        wins=bot.wins,
        losses=bot.losses,
        kills=bot.kills,
        deaths=bot.deaths,
    )
