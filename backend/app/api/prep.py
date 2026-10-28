"""Interview prep plans for your applications."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Application, Interview, User
from ..security import audit, current_user, owned, rate_limit
from ..services import applications as appsvc
from ..services import interview_prep, llm
from ..services.matching import latest_assessment

router = APIRouter(prefix="/api", tags=["prep"])


def _resume_text(db: Session, app: Application) -> str:
    r = appsvc.master_resume(db, app.user_id)
    return r.text if r is not None else ""


def build_for(db: Session, app: Application, use_ai: bool = False) -> dict:
    m = latest_assessment(db, app.job_id)
    ivs = [{"scheduled_at": i.scheduled_at, "stage": i.stage} for i in db.query(Interview).filter_by(application_id=app.id).all()]
    text = _resume_text(db, app)
    prep = interview_prep.build(app.job, text, {"breakdown": m.breakdown} if m else None, ivs)
    old = app.prep or {}
    prep["done"] = [t for t in old.get("done", []) if any(p["id"] == t for p in prep["plan"])]
    prep["ai_questions"] = old.get("ai_questions", [])
    prep["ai_note"] = ""
    if use_ai:
        cfg = llm.config_for(db, app.user_id)
        if cfg is None:
            prep["ai_note"] = "Connect an AI model in Settings → Connections to add questions written for this exact posting."
        else:
            try:
                prep["ai_questions"] = interview_prep.ai_questions(cfg, app.job, text, prep)
                prep["source"] = "rules+ai:" + cfg.model
            except llm.LLMError as e:
                prep["ai_note"] = f"AI questions unavailable right now ({e})."
    app.prep = prep
    return prep


@router.get("/applications/{aid}/prep")
def get_prep(aid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = owned(db, Application, aid, user)
    if not app.prep:
        build_for(db, app)
        db.commit()
    return {"prep": app.prep, "job": {"id": app.job.id, "title": app.job.title, "company": app.job.company}, "status": app.status}


class Regen(BaseModel):
    use_ai: bool = False


@router.post("/applications/{aid}/prep", dependencies=[Depends(rate_limit("prep", 30, 3600))])
def regenerate(aid: int, body: Regen, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = owned(db, Application, aid, user)
    prep = build_for(db, app, use_ai=body.use_ai)
    audit(db, user.id, "prep.generate", "application", app.id, ai=body.use_ai)
    db.commit()
    return {"prep": prep}


class Progress(BaseModel):
    done: list[str] = Field(default_factory=list, max_length=200)


@router.put("/applications/{aid}/prep/progress")
def progress(aid: int, body: Progress, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = owned(db, Application, aid, user)
    if not app.prep:
        raise HTTPException(404, "No prep plan yet.")
    ids = {t["id"] for t in app.prep.get("plan", [])}
    app.prep = {**app.prep, "done": [d for d in body.done if d in ids]}
    db.commit()
    return {"done": app.prep["done"]}
