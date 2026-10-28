"""Priority companies (hourly checks in your alert window) and email alerts."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db, session_scope
from ..models import IntegrationSetting, JobSource, User, UserSettings, to_dict, utcnow
from ..security import audit, current_user, owned, rate_limit
from ..services import notify, priority
from ..services.secretbox import mask, seal, unseal

router = APIRouter(prefix="/api", tags=["alerts"])


def _settings(db: Session, user: User) -> UserSettings:
    st = db.get(UserSettings, user.id)
    if st is None:
        st = UserSettings(user_id=user.id)
        db.add(st)
        db.flush()
    return st


def _email_status(db: Session, user: User) -> dict:
    row = db.query(IntegrationSetting).filter_by(user_id=user.id, provider="email").one_or_none()
    d = unseal(row.data_encrypted) if row else {}
    return {"configured": bool(d.get("resend_key") and d.get("to")), "to": d.get("to", ""), "key_hint": mask(d.get("resend_key", ""))}


@router.get("/priority")
def get_priority(user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = _settings(db, user)
    db.commit()
    cfg = priority.config(st)
    comps = db.query(JobSource).filter(JobSource.user_id == user.id, JobSource.priority.is_(True)).order_by(JobSource.display_name).all()
    return {"config": cfg, "configured": st.priority_alerts is not None, "companies": [to_dict(c) for c in comps],
            "last_run_at": st.priority_last_run_at.isoformat() + "Z" if st.priority_last_run_at else None,
            "last_result": st.priority_last_result, "in_window_now": priority.in_window(cfg),
            "email": _email_status(db, user), "running": priority_running(user.id)}


class PriorityConfig(BaseModel):
    enabled: bool = True
    start_hour: int = Field(10, ge=0, le=23)
    end_hour: int = Field(17, ge=0, le=23)
    days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4], max_length=7)
    timezone: str = Field("America/New_York", max_length=60)
    min_score: int = Field(0, ge=0, le=100)
    email: bool = True


@router.put("/priority")
def put_priority(body: PriorityConfig, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from zoneinfo import ZoneInfo

    try:
        ZoneInfo(body.timezone)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Unknown time zone.")
    if body.end_hour < body.start_hour:
        raise HTTPException(400, "The end hour must be after the start hour.")
    st = _settings(db, user)
    st.priority_alerts = {**body.model_dump(), "days": sorted({d for d in body.days if 0 <= d <= 6})}
    audit(db, user.id, "priority.settings", "user", user.id)
    db.commit()
    return get_priority(user, db)


class StarIn(BaseModel):
    on: bool = True


@router.post("/companies/{sid}/priority")
def star_company(sid: int, body: StarIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    src = owned(db, JobSource, sid, user)
    src.priority = body.on
    st = _settings(db, user)
    if body.on and st.priority_alerts is None:
        st.priority_alerts = dict(priority.DEFAULTS)  # turn alerts on with the default window
    audit(db, user.id, "priority.star" if body.on else "priority.unstar", "job_source", src.id)
    db.commit()
    return {"ok": True, "priority": src.priority}


_running: set[int] = set()


def priority_running(uid: int) -> bool:
    return uid in _running


@router.post("/priority/run", dependencies=[Depends(rate_limit("priority-run", 12, 3600))])
def run_now(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Check your priority companies now (in the background) and email anything new."""
    from ..scheduler import user_lock

    if not db.query(JobSource).filter(JobSource.user_id == user.id, JobSource.priority.is_(True)).count():
        raise HTTPException(400, "Mark at least one company as ★ priority first.")
    lock = user_lock(user.id)
    if not lock.acquire(blocking=False):
        return {"started": False, "running": True}
    _running.add(user.id)

    def work(uid=user.id):
        try:
            with session_scope() as bg:
                priority.run_for_user(bg, uid)
        finally:
            _running.discard(uid)
            lock.release()

    threading.Thread(target=work, daemon=True).start()
    return {"started": True}


_cron = threading.Lock()


@router.api_route("/cron/priority", methods=["GET", "POST"], include_in_schema=False)
def cron(request: Request):
    """Called every hour by the GitHub Actions schedule (wakes the free server). Runs whatever is due; returns no data."""
    if not _cron.acquire(blocking=False):
        return {"started": False, "running": True}

    def work():
        try:
            priority.tick_all(session_scope)
        finally:
            _cron.release()

    threading.Thread(target=work, daemon=True).start()
    return {"started": True, "at": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------- email connection (Resend)

class EmailIn(BaseModel):
    resend_key: str = Field(default="", max_length=200)
    to: str = Field(default="", max_length=320)


@router.put("/integrations/email")
def save_email(body: EmailIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.query(IntegrationSetting).filter_by(user_id=user.id, provider="email").one_or_none()
    old = unseal(row.data_encrypted) if row else {}
    key = body.resend_key.strip() or old.get("resend_key", "")
    to = body.to.strip() or old.get("to", "") or user.email
    if not key.startswith("re_"):
        raise HTTPException(400, "That doesn't look like a Resend API key (it starts with re_).")
    if "@" not in to:
        raise HTTPException(400, "Enter the email address to send alerts to.")
    data = {"resend_key": key, "to": to}
    if row is None:
        db.add(IntegrationSetting(user_id=user.id, provider="email", data_encrypted=seal(data)))
    else:
        row.data_encrypted, row.updated_at = seal(data), utcnow()
    audit(db, user.id, "integration.save", "integration", None, provider="email")
    db.commit()
    return _email_status(db, user)


@router.post("/integrations/email/test", dependencies=[Depends(rate_limit("email-test", 10, 3600))])
def test_email(user: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = notify.email_config(db, user.id)
    if cfg is None:
        raise HTTPException(400, "Save your Resend key first.")
    try:
        notify.send_email(cfg, "✅ JobPilot email alerts are working",
                          "<p>This is a test from JobPilot. You'll get an email like this when a priority company posts a role that matches your profile.</p>",
                          "This is a test from JobPilot. Email alerts are working.")
    except notify.EmailError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "message": f"Test email sent to {cfg['to']}. Check your inbox (and spam folder)."}
