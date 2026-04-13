"""Simple session-based auth: username/password, cookie session."""
from fastapi import Request, HTTPException, Depends
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .db import get_db
from . import models


pwd = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(raw: str) -> str:
    return pwd.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return pwd.verify(raw, hashed)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    uid = request.session.get("uid")
    if not uid:
        raise HTTPException(401, "Not authenticated")
    user = db.get(models.User, uid)
    if not user:
        raise HTTPException(401, "Invalid session")
    return user


def require_company(
    company_id: int | None,
    user: models.User = Depends(get_current_user),
) -> int:
    """If caller passed a company_id it MUST match their own. Returns effective company_id."""
    if company_id is not None and company_id != user.company_id:
        raise HTTPException(403, "Forbidden")
    return user.company_id
