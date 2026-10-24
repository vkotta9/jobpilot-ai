from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import CandidateProfile, User, UserSettings
from ..schemas import Credentials
from ..security import (
    SESSION_COOKIE,
    audit,
    create_session,
    current_user,
    hash_password,
    rate_limit,
    revoke_session,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

DEFAULT_WORKFLOWS = {"discovery": True, "follow_up_tasks": True, "digest": True}


def _set_cookie(resp: Response, token: str, request: Request) -> None:
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict",
                    secure=request.url.scheme == "https", max_age=settings.session_days * 86400, path="/")


@router.post("/register", dependencies=[Depends(rate_limit("auth", 10, 60))])
def register(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    if not settings.allow_registration:
        raise HTTPException(403, "Registration is disabled on this instance.")
    if db.query(User).filter_by(email=body.email).first():
        raise HTTPException(409, "An account with this email already exists.")
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    db.add(UserSettings(user_id=user.id, workflows=dict(DEFAULT_WORKFLOWS)))
    db.add(CandidateProfile(user_id=user.id, email=body.email))
    audit(db, user.id, "auth.register")
    db.commit()
    token = create_session(db, user)
    _set_cookie(response, token, request)
    return {"user": {"id": user.id, "email": user.email}, "token": token}


@router.post("/login", dependencies=[Depends(rate_limit("auth", 10, 60))])
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        audit(db, user.id if user else None, "auth.login_failed")
        db.commit()
        raise HTTPException(401, "Incorrect email or password.")
    audit(db, user.id, "auth.login")
    db.commit()
    token = create_session(db, user)
    _set_cookie(response, token, request)
    return {"user": {"id": user.id, "email": user.email}, "token": token}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE) or request.headers.get("authorization", "")[7:]
    if token:
        revoke_session(db, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email}
