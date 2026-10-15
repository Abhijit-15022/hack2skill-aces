"""Demo-grade auth: sign in by email, get a signed token. Swap for Google Identity Platform in production."""
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterator

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .config import get_settings
from .db import org_session
from .services.core import now

settings = get_settings()


@dataclass
class Ctx:
    db: Session
    user: m.User
    org_id: int


def issue_token(user: m.User) -> str:
    payload = {"uid": user.id, "org": user.org_id, "exp": now() + timedelta(days=7)}
    return jwt.encode(payload, settings.relay_secret, algorithm="HS256")


def find_user_any_org(email: str) -> m.User | None:
    with org_session(None, bypass=True) as db:
        return db.scalar(select(m.User).where(m.User.email == email.lower(), m.User.kind == "human"))


def ctx(authorization: str = Header(default="")) -> Iterator[Ctx]:
    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = jwt.decode(token, settings.relay_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Sign in again: the token is missing or expired.")
    with org_session(claims["org"]) as db:
        user = db.get(m.User, claims["uid"])
        if user is None:
            raise HTTPException(401, "This user no longer exists.")
        yield Ctx(db=db, user=user, org_id=claims["org"])


def admin_ctx(c: Ctx = Depends(ctx)) -> Ctx:
    if not c.user.is_org_admin:
        raise HTTPException(403, "Only organisation admins can do this.")
    return c


def require_ingest_token(x_relay_token: str = Header(default="")) -> None:
    if x_relay_token != settings.relay_ingest_token:
        raise HTTPException(401, "Missing or wrong X-Relay-Token.")
