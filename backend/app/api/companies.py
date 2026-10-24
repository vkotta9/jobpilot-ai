"""Follow companies by careers-page link or company name, plus a popular-companies list."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import JobSource, User, to_dict
from ..security import audit, current_user, rate_limit
from ..services.discovery import run_source
from ..services.matching import score_jobs
from ..services.sources import COMPANY_KINDS
from ..services.sources.catalog import POPULAR, TOP_TECH
from ..services.sources.detect import detect_many

router = APIRouter(prefix="/api/companies", tags=["companies"])


class DetectIn(BaseModel):
    entries: list[str] = Field(min_length=1, max_length=60)


class FollowItem(BaseModel):
    kind: str
    identifier: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.%&|' \-]+$")
    company: str = Field(default="", max_length=200)


class FollowIn(BaseModel):
    items: list[FollowItem] = Field(min_length=1, max_length=150)
    run_now: bool = True


@router.post("/detect", dependencies=[Depends(rate_limit("company-detect", 20, 3600))])
def detect(body: DetectIn, user: User = Depends(current_user)):
    return [d.dict() for d in detect_many([e[:500] for e in body.entries])]


def _follow(db: Session, user: User, items: list[FollowItem], run_now: bool) -> dict:
    added, existing, results = [], 0, []
    for it in items:
        if it.kind not in COMPANY_KINDS and it.kind != "jsearch":
            raise HTTPException(400, f"Unsupported board type: {it.kind}")
        if it.kind == "jsearch" and it.identifier.lower() == "auto":
            raise HTTPException(400, "Invalid company.")
        ident = it.identifier if it.kind in ("smartrecruiters", "ashby", "workday", "jsearch", "eightfold", "oraclehcm") else it.identifier.lower()
        src = db.query(JobSource).filter_by(user_id=user.id, kind=it.kind, identifier=ident).one_or_none()
        if src:
            existing += 1
            src.enabled = True
            continue
        src = JobSource(user_id=user.id, kind=it.kind, identifier=ident, display_name=it.company or ident)
        db.add(src)
        db.flush()
        added.append(src)
    audit(db, user.id, "companies.follow", "job_source", None, added=len(added))
    db.commit()
    changed: list[int] = []
    if run_now and len(added) > 8:
        # many companies: search them in the background so the request returns right away
        import threading

        from ..db import session_scope
        from ..scheduler import user_lock

        ids, lock = [s.id for s in added], user_lock(user.id)
        if lock.acquire(blocking=False):
            def work(uid=user.id, ids=ids):
                try:
                    with session_scope() as bg:
                        ch: list[int] = []
                        for sid in ids:
                            src = bg.get(JobSource, sid)
                            if src is None:
                                continue
                            try:
                                ch += run_source(bg, src).pop("changed_job_ids", []) or []
                            except Exception:  # noqa: BLE001 - one bad source mustn't stop the rest
                                bg.rollback()
                        if ch:
                            score_jobs(bg, uid, ch)
                finally:
                    lock.release()

            threading.Thread(target=work, daemon=True).start()
            return {"added": len(added), "already_following": existing, "results": [], "background": True, "pending": 0}
        return {"added": len(added), "already_following": existing, "results": [], "pending": len(added)}
    if run_now:
        for src in added[:40]:  # big lists finish on the next scheduled run
            r = run_source(db, src)
            changed += r.pop("changed_job_ids", []) or []
            results.append({"company": src.display_name, **{k: r.get(k) for k in ("new", "matching", "on_board", "error")}})
        if changed:
            score_jobs(db, user.id, changed)
    return {"added": len(added), "already_following": existing, "results": results,
            "pending": max(0, len(added) - 40) if run_now else len(added)}


@router.post("/follow", dependencies=[Depends(rate_limit("company-follow", 30, 3600))])
def follow(body: FollowIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _follow(db, user, body.items, body.run_now)


@router.get("")
def following(user: User = Depends(current_user), db: Session = Depends(get_db)):
    from sqlalchemy import and_, or_

    rows = db.query(JobSource).filter(JobSource.user_id == user.id, or_(
        JobSource.kind.in_(COMPANY_KINDS), and_(JobSource.kind == "jsearch", JobSource.identifier != "auto"))).order_by(JobSource.display_name).all()
    return [to_dict(s) for s in rows]


@router.get("/popular")
def popular(user: User = Depends(current_user), db: Session = Depends(get_db)):
    followed = {(s.kind, s.identifier.lower()) for s in db.query(JobSource).filter(JobSource.user_id == user.id).all()}
    return [dict(c, following=(c["kind"], c["identifier"].lower()) in followed) for c in POPULAR]


@router.get("/top-tech")
def top_tech(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The top-100 tech companies: direct careers feeds where available, Google Jobs (JSearch) for the rest."""
    from ..models import IntegrationSetting

    followed = {(s.kind, s.identifier.lower()) for s in db.query(JobSource).filter(JobSource.user_id == user.id).all()}
    has_jsearch = db.query(IntegrationSetting).filter_by(user_id=user.id, provider="jsearch").count() > 0
    return {"jsearch_connected": has_jsearch,
            "companies": [dict(c, following=(c["kind"], c["identifier"].lower()) in followed) for c in TOP_TECH]}
