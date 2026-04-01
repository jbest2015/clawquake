import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_db, get_current_user_or_apikey
from models import BotDB, BotRegister, BotResponse, BotUpdate, UserDB

router = APIRouter(tags=["bots"])

# Resolve available strategies from the strategies/ directory
STRATEGIES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "strategies")
if not os.path.isdir(STRATEGIES_DIR):
    # Inside Docker container: /app/strategies
    STRATEGIES_DIR = "/app/strategies"


def _list_strategies() -> list[str]:
    """Return list of available strategy stems (filenames without .py)."""
    if not os.path.isdir(STRATEGIES_DIR):
        return ["default"]
    return sorted(
        f[:-3] for f in os.listdir(STRATEGIES_DIR)
        if f.endswith(".py") and not f.startswith("_")
    )


def _normalize_strategy_name(strategy: str) -> str:
    return strategy.strip().lower().replace(" ", "_")


@router.get("/api/strategies")
def list_strategies():
    """List available strategy names that can be assigned to bots."""
    return {"strategies": _list_strategies()}


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

    # Validate strategy
    strategy = _normalize_strategy_name(payload.strategy)
    available = _list_strategies()
    if strategy not in available:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy '{strategy}'. Available: {available}",
        )

    bot = BotDB(name=name, owner_id=user.id, strategy=strategy)
    db.add(bot)
    db.commit()
    db.refresh(bot)

    return BotResponse(
        id=bot.id,
        name=bot.name,
        strategy=bot.strategy,
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
            strategy=bot.strategy or "default",
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
        strategy=bot.strategy or "default",
        elo=bot.elo,
        wins=bot.wins,
        losses=bot.losses,
        kills=bot.kills,
        deaths=bot.deaths,
    )


@router.patch("/api/bots/{bot_id}", response_model=BotResponse)
def update_bot(
    bot_id: int,
    payload: BotUpdate,
    user: UserDB = Depends(get_current_user_or_apikey),
    db: Session = Depends(get_db),
):
    bot = db.query(BotDB).filter(BotDB.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    strategy = _normalize_strategy_name(payload.strategy)
    available = _list_strategies()
    if strategy not in available:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy '{strategy}'. Available: {available}",
        )

    bot.strategy = strategy
    db.commit()
    db.refresh(bot)

    return BotResponse(
        id=bot.id,
        name=bot.name,
        strategy=bot.strategy or "default",
        elo=bot.elo,
        wins=bot.wins,
        losses=bot.losses,
        kills=bot.kills,
        deaths=bot.deaths,
    )
