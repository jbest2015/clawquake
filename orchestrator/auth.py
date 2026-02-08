import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from api_keys import hash_api_key
from models import UserDB, SessionLocal
from models import ApiKeyDB

SECRET_KEY = os.environ.get("JWT_SECRET")
if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET environment variable is required. Set it before starting the server.")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> UserDB:
    token = credentials.credentials
    return _get_user_from_token(token, db)


def _get_user_from_token(token: str, db: Session) -> UserDB:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(UserDB).filter(UserDB.username == username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_current_user_or_apikey(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> UserDB:
    """
    Authenticate with either a Bearer JWT token or an X-API-Key header.
    Returns the owning user in both cases.
    """
    if credentials and credentials.scheme.lower() == "bearer":
        return _get_user_from_token(credentials.credentials, db)

    if x_api_key:
        key_hash = hash_api_key(x_api_key)
        key = (
            db.query(ApiKeyDB)
            .filter(ApiKeyDB.key_hash == key_hash, ApiKeyDB.is_active == 1)
            .first()
        )
        if not key:
            raise HTTPException(status_code=401, detail="Invalid API key")

        # Check expiry
        if key.expires_at and key.expires_at < datetime.utcnow():
            raise HTTPException(status_code=401, detail="API key has expired")

        user = db.query(UserDB).filter(UserDB.id == key.user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        key.last_used = datetime.utcnow()
        db.commit()
        return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


def require_admin(user: UserDB = Depends(get_current_user)) -> UserDB:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
