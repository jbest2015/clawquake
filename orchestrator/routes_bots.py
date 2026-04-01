import os
import re

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_db, get_current_user_or_apikey
from models import BotDB, BotRegister, BotResponse, BotUpdate, UserDB

router = APIRouter(tags=["bots"])

# Resolve available strategies from the strategies/ directory
STRATEGIES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "strategies")
if not os.path.isdir(STRATEGIES_DIR):
    STRATEGIES_DIR = "/app/strategies"

CUSTOM_STRATEGIES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "custom_strategies")
if not os.path.isdir(CUSTOM_STRATEGIES_DIR):
    CUSTOM_STRATEGIES_DIR = "/app/custom_strategies"
    os.makedirs(CUSTOM_STRATEGIES_DIR, exist_ok=True)

MAX_STRATEGY_SIZE = 50 * 1024  # 50KB
MAX_CUSTOM_PER_USER = 10
STRATEGY_NAME_PATTERN = re.compile(r"^[a-z0-9_]{1,40}$")

# Dangerous patterns to reject in custom strategies
DANGEROUS_PATTERNS = [
    r"\bimport\s+os\b", r"\bimport\s+sys\b", r"\bimport\s+subprocess\b",
    r"\bimport\s+shutil\b", r"\bimport\s+socket\b", r"\bimport\s+requests\b",
    r"\bimport\s+urllib\b", r"\bimport\s+http\b", r"\bimport\s+pathlib\b",
    r"\b__import__\s*\(", r"\beval\s*\(", r"\bexec\s*\(",
    r"\bopen\s*\(", r"\bos\.", r"\bsys\.", r"\bsubprocess\.",
    r"\bglobals\s*\(", r"\blocals\s*\(", r"\bgetattr\s*\(",
    r"\bsetattr\s*\(", r"\bdelattr\s*\(", r"\bcompile\s*\(",
]


def _list_strategies() -> list[str]:
    """Return list of available global strategy stems."""
    if not os.path.isdir(STRATEGIES_DIR):
        return ["default"]
    return sorted(
        f[:-3] for f in os.listdir(STRATEGIES_DIR)
        if f.endswith(".py") and not f.startswith("_")
    )


def _list_custom_strategies(user_id: int) -> list[str]:
    """Return list of custom strategy names for a specific user."""
    if not os.path.isdir(CUSTOM_STRATEGIES_DIR):
        return []
    prefix = f"{user_id}_"
    return sorted(
        f[len(prefix):-3] for f in os.listdir(CUSTOM_STRATEGIES_DIR)
        if f.startswith(prefix) and f.endswith(".py")
    )


def _custom_strategy_path(user_id: int, name: str) -> str:
    return os.path.join(CUSTOM_STRATEGIES_DIR, f"{user_id}_{name}.py")


def _normalize_strategy_name(strategy: str) -> str:
    return strategy.strip().lower().replace(" ", "_")


def _is_valid_strategy(strategy: str, user_id: int) -> bool:
    """Check if a strategy name is valid (global or custom:name owned by user)."""
    if strategy.startswith("custom:"):
        custom_name = strategy[7:]
        return os.path.exists(_custom_strategy_path(user_id, custom_name))
    return strategy in _list_strategies()


def _validate_strategy_source(source: str) -> list[str]:
    """Validate custom strategy source code. Returns list of errors."""
    errors = []

    if len(source.encode("utf-8")) > MAX_STRATEGY_SIZE:
        errors.append(f"Strategy too large (max {MAX_STRATEGY_SIZE // 1024}KB)")
        return errors

    # Must compile as valid Python
    try:
        compile(source, "<custom_strategy>", "exec")
    except SyntaxError as e:
        errors.append(f"Syntax error: {e}")
        return errors

    # Check for dangerous patterns
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, source):
            errors.append(f"Forbidden pattern detected: {pattern}")

    # Must define required exports
    ns = {}
    try:
        exec(compile(source, "<validation>", "exec"), {"__builtins__": {}}, ns)
    except Exception:
        pass  # We just check for the names; runtime errors are OK at validation time

    # Check source text for required definitions (more reliable than exec with no builtins)
    if "STRATEGY_NAME" not in source:
        errors.append("Missing STRATEGY_NAME")
    if "STRATEGY_VERSION" not in source:
        errors.append("Missing STRATEGY_VERSION")
    if "def on_spawn" not in source:
        errors.append("Missing on_spawn() function")
    if "def tick" not in source and "async def tick" not in source:
        errors.append("Missing tick() function")

    return errors


@router.get("/api/strategies")
def list_strategies(
    user: UserDB = Depends(get_current_user_or_apikey),
):
    """List available strategies (global + user's custom)."""
    return {
        "strategies": _list_strategies(),
        "custom": _list_custom_strategies(user.id),
    }


@router.get("/api/strategies/{name}")
def get_strategy_source(
    name: str,
    user: UserDB = Depends(get_current_user_or_apikey),
):
    """Download the source code of a strategy."""
    # Check custom first
    custom_path = _custom_strategy_path(user.id, name)
    if os.path.exists(custom_path):
        with open(custom_path, "r") as f:
            return {"name": name, "source": f.read(), "type": "custom"}

    # Check global
    global_path = os.path.join(STRATEGIES_DIR, f"{name}.py")
    if os.path.exists(global_path):
        with open(global_path, "r") as f:
            return {"name": name, "source": f.read(), "type": "global"}

    raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")


class StrategyUpload(BaseModel):
    source: str


@router.put("/api/strategies/custom/{name}")
def upload_custom_strategy(
    name: str,
    payload: StrategyUpload,
    user: UserDB = Depends(get_current_user_or_apikey),
):
    """Upload or update a custom strategy (scoped to user's bots only)."""
    name = _normalize_strategy_name(name)

    if not STRATEGY_NAME_PATTERN.match(name):
        raise HTTPException(
            status_code=400,
            detail="Strategy name must be 1-40 chars, lowercase alphanumeric + underscore only",
        )

    # Check rate limit
    existing_custom = _list_custom_strategies(user.id)
    if name not in existing_custom and len(existing_custom) >= MAX_CUSTOM_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_CUSTOM_PER_USER} custom strategies per user",
        )

    # Validate source code
    errors = _validate_strategy_source(payload.source)
    if errors:
        raise HTTPException(status_code=400, detail={"validation_errors": errors})

    # Write to disk
    os.makedirs(CUSTOM_STRATEGIES_DIR, exist_ok=True)
    path = _custom_strategy_path(user.id, name)
    with open(path, "w") as f:
        f.write(payload.source)

    return {
        "name": name,
        "type": "custom",
        "assign_as": f"custom:{name}",
        "message": f"Custom strategy '{name}' saved. Assign to a bot with strategy='custom:{name}'",
    }


@router.delete("/api/strategies/custom/{name}")
def delete_custom_strategy(
    name: str,
    user: UserDB = Depends(get_current_user_or_apikey),
):
    """Delete a custom strategy."""
    name = _normalize_strategy_name(name)
    path = _custom_strategy_path(user.id, name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Custom strategy '{name}' not found")
    os.remove(path)
    return {"deleted": True, "name": name}


@router.get("/api/strategies/custom")
def list_custom_strategies(
    user: UserDB = Depends(get_current_user_or_apikey),
):
    """List user's custom strategies with metadata."""
    customs = _list_custom_strategies(user.id)
    result = []
    for name in customs:
        path = _custom_strategy_path(user.id, name)
        size = os.path.getsize(path) if os.path.exists(path) else 0
        result.append({"name": name, "assign_as": f"custom:{name}", "size_bytes": size})
    return {"custom_strategies": result}


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

    # Validate strategy (global or custom:name)
    strategy = _normalize_strategy_name(payload.strategy)
    if not _is_valid_strategy(strategy, user.id):
        available = _list_strategies()
        custom = _list_custom_strategies(user.id)
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy '{strategy}'. Global: {available}. Custom: {['custom:'+c for c in custom]}",
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
    if not _is_valid_strategy(strategy, user.id):
        available = _list_strategies()
        custom = _list_custom_strategies(user.id)
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy '{strategy}'. Global: {available}. Custom: {['custom:'+c for c in custom]}",
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
