"""Dashboard, analytics, tasks, settings, automation pause, health, data export/deletion."""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from ..db import get_db
from ..schemas import SettingsIn, TaskIn
from ..security import audit, current_user, owned
from ..services import llm
from ..services.insights import analytics, attention_items, digest

router = APIRouter(prefix="/api", tags=["misc"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "database_backend": settings.database_url.split(":", 1)[0],
        "llm": {"configured": llm.available(), "model": settings.openai_model if llm.available() else None,
                "note": "Users can also connect their own AI key in Settings → Connections."},
        "simulated_sources_allowed": settings.allow_mock_sources,
        "scheduler_enabled": settings.scheduler_enabled,
    }


@router.get("/dashboard")
def dashboard(user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    a = analytics(db, user.id, include_simulated=True)
    st = db.get(M.UserSettings, user.id)
    return {
        "counts": a["counts"],
        "status_counts": a["status_counts"],
        "digest": digest(db, user.id, 7),
        "automation_paused": st.automation_paused if st else False,
        "last_auto_search_at": st.last_auto_search_at.isoformat() + "Z" if st and st.last_auto_search_at else None,
        "has_profile": bool(db.query(M.CandidateProfile).filter_by(user_id=user.id).one().experience),
        "has_resume": db.query(M.Resume).filter_by(user_id=user.id).count() > 0,
        "has_sources": db.query(M.JobSource).filter_by(user_id=user.id).count() > 0,
        "llm_configured": llm.config_for(db, user.id) is not None,
    }


@router.get("/analytics")
def get_analytics(include_simulated: bool = False, user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    return analytics(db, user.id, include_simulated)


@router.get("/digest")
def get_digest(days: int = 7, user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    return digest(db, user.id, max(1, min(days, 31)))


@router.get("/attention")
def attention(user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    return attention_items(db, user.id)


# ---------------------------------------------------------------- tasks


@router.get("/tasks")
def tasks(include_done: bool = False, user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(M.FollowUpTask).filter_by(user_id=user.id)
    if not include_done:
        q = q.filter_by(done=False)
    now = M.utcnow()
    out = []
    for t in q.order_by(M.FollowUpTask.due_at).all():
        d = M.to_dict(t)
        d["overdue"] = (not t.done) and t.due_at < now
        if t.application_id:
            a = db.get(M.Application, t.application_id)
            d["job"] = {"id": a.job.id, "title": a.job.title, "company": a.job.company} if a else None
        out.append(d)
    return out


@router.post("/tasks")
def add_task(body: TaskIn, user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    if body.application_id:
        owned(db, M.Application, body.application_id, user)
    try:
        due = datetime.fromisoformat(body.due_at.replace("Z", "")[:19])
    except ValueError:
        raise HTTPException(400, "Invalid due date")
    t = M.FollowUpTask(user_id=user.id, application_id=body.application_id, title=body.title, due_at=due, kind="custom")
    db.add(t)
    db.commit()
    return M.to_dict(t)


@router.post("/tasks/{tid}/done")
def done_task(tid: int, done: bool = True, user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, M.FollowUpTask, tid, user)
    t.done = done
    db.commit()
    return M.to_dict(t)


@router.post("/tasks/{tid}/snooze")
def snooze(tid: int, days: int = 2, user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, M.FollowUpTask, tid, user)
    t.due_at = max(t.due_at, M.utcnow()) + timedelta(days=max(1, min(days, 30)))
    db.commit()
    return M.to_dict(t)


@router.delete("/tasks/{tid}")
def del_task(tid: int, user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(owned(db, M.FollowUpTask, tid, user))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- settings


def _settings(db: Session, user: M.User) -> M.UserSettings:
    st = db.get(M.UserSettings, user.id)
    if st is None:
        st = M.UserSettings(user_id=user.id, workflows={"discovery": True, "follow_up_tasks": True, "digest": True})
        db.add(st)
        db.flush()
    return st


@router.get("/settings")
def get_settings(user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    st = _settings(db, user)
    db.commit()
    return M.to_dict(st)


@router.put("/settings")
def put_settings(body: SettingsIn, user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    st = _settings(db, user)
    for k, v in body.model_dump(exclude_none=True).items():
        if k == "workflows":
            v = {**(st.workflows or {}), **{kk: bool(vv) for kk, vv in v.items() if kk in ("discovery", "follow_up_tasks", "digest")}}
        setattr(st, k, v)
    audit(db, user.id, "settings.update", detail_keys=sorted(body.model_dump(exclude_none=True)))
    db.commit()
    return M.to_dict(st)


@router.post("/automation/pause")
def pause(user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    st = _settings(db, user)
    st.automation_paused = True
    audit(db, user.id, "automation.pause")
    db.commit()
    return {"automation_paused": True}


@router.post("/automation/resume")
def resume(user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    st = _settings(db, user)
    st.automation_paused = False
    audit(db, user.id, "automation.resume")
    db.commit()
    return {"automation_paused": False}


@router.get("/audit-log")
def audit_log(user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(M.AuditLog).filter_by(user_id=user.id).order_by(M.AuditLog.id.desc()).limit(200).all()
    return [M.to_dict(r) for r in rows]


# ---------------------------------------------------------------- privacy

_EXPORT_TABLES = [M.IntegrationSetting, M.CandidateProfile, M.ProfileRevision, M.UserSettings, M.Resume, M.JobSource, M.SavedSearch, M.Job,
                  M.MatchAssessment, M.Application, M.Document, M.ScreeningAnswer, M.Contact, M.OutreachMessage,
                  M.FollowUpTask, M.Interview, M.ApplicationEvent, M.AuditLog]


@router.get("/account/export")
def export_all(user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    data = {"user": {"id": user.id, "email": user.email, "created_at": user.created_at.isoformat() + "Z"},
            "exported_at": M.utcnow().isoformat() + "Z"}
    for model in _EXPORT_TABLES:
        if model is M.UserSettings:
            st = db.get(M.UserSettings, user.id)
            data["user_settings"] = [M.to_dict(st)] if st else []
            continue
        exclude = ("storage_name",) if model is M.Resume else ()
        if model in (M.JobSnapshot,):
            continue
        data[model.__tablename__] = [M.to_dict(r, exclude=exclude) for r in db.query(model).filter_by(user_id=user.id).all()]
    audit(db, user.id, "account.export")
    db.commit()
    from fastapi.responses import JSONResponse

    return JSONResponse(data, headers={"Content-Disposition": 'attachment; filename="jobpilot_export.json"'})


@router.delete("/account")
def delete_account(confirm_email: str, user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    if confirm_email.strip().lower() != user.email:
        raise HTTPException(400, "Type your account email to confirm deletion.")
    # Explicit ordered deletes (works with or without DB-level cascades)
    for model in [M.OutreachMessage, M.FollowUpTask, M.Interview, M.ApplicationEvent, M.ScreeningAnswer, M.Contact]:
        db.query(model).filter_by(user_id=user.id).delete(synchronize_session=False)
    db.query(M.Application).filter_by(user_id=user.id).delete(synchronize_session=False)
    db.query(M.Document).filter_by(user_id=user.id).delete(synchronize_session=False)
    db.query(M.MatchAssessment).filter_by(user_id=user.id).delete(synchronize_session=False)
    job_ids = [j for (j,) in db.query(M.Job.id).filter_by(user_id=user.id).all()]
    if job_ids:
        db.query(M.JobSnapshot).filter(M.JobSnapshot.job_id.in_(job_ids)).delete(synchronize_session=False)
        db.query(M.Job).filter_by(user_id=user.id).update({"duplicate_of_id": None}, synchronize_session=False)
    for model in [M.Job, M.SavedSearch, M.JobSource, M.Resume, M.ProfileRevision, M.CandidateProfile,
                  M.AuthSession, M.AuditLog, M.IntegrationSetting]:
        db.query(model).filter_by(user_id=user.id).delete(synchronize_session=False)
    db.query(M.UserSettings).filter_by(user_id=user.id).delete(synchronize_session=False)
    db.query(M.User).filter_by(id=user.id).delete(synchronize_session=False)
    db.commit()
    shutil.rmtree(settings.upload_dir / str(user.id), ignore_errors=True)
    return {"ok": True, "deleted": True}
