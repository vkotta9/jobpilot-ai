"""Authentication, authorization helpers, rate limiting and audit logging."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Optional, Type, TypeVar

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import AuditLog, AuthSession, User, utcnow

SESSION_COOKIE = "jp_session"
T = TypeVar("T")

# ---------------------------------------------------------------- passwords

_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_hex, digest_hex = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


# ---------------------------------------------------------------- sessions


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            token_hash=_hash_token(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(days=settings.session_days),
        )
    )
    db.commit()
    return token


def revoke_session(db: Session, token: str) -> None:
    db.query(AuthSession).filter(AuthSession.token_hash == _hash_token(token)).delete()
    db.commit()


def _extract_token(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(SESSION_COOKIE)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    sess = db.get(AuthSession, _hash_token(token))
    if not sess or sess.expires_at < utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    user = db.get(User, sess.user_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    request.state.user_id = user.id
    return user


def owned(db: Session, model: Type[T], obj_id: int, user: User) -> T:
    """Fetch a row by id *only if it belongs to the user*; 404 otherwise.

    Returning 404 (not 403) avoids leaking the existence of other users' rows.
    """
    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, "user_id", None) != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} not found")
    return obj


# ---------------------------------------------------------------- rate limiting


class RateLimiter:
    """Sliding-window in-memory limiter (per process). Fine for a single-node MVP."""

    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_s: int) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    f"Too many requests. Try again in {int(window_s - (now - q[0])) + 1}s.",
                )
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def rate_limit(name: str, limit: int, window_s: int):
    def dep(request: Request) -> None:
        who = getattr(request.state, "user_id", None) or (request.client.host if request.client else "anon")
        limiter.check(f"{name}:{who}", limit, window_s)

    return dep


# ---------------------------------------------------------------- audit

_REDACT_KEYS = {"password", "token", "api_key", "secret", "authorization"}


def _redact(detail: dict) -> dict:
    return {k: ("[redacted]" if k.lower() in _REDACT_KEYS else v) for k, v in (detail or {}).items()}


def audit(db: Session, user_id: Optional[int], action: str, entity: str = "", entity_id: Optional[int] = None, **detail) -> None:
    db.add(AuditLog(user_id=user_id, action=action, entity=entity, entity_id=entity_id, detail=_redact(detail)))
