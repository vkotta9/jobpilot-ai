"""Role tracks: up to three resumes, each aimed at one kind of role (Software Engineer, ML Engineer, Data Scientist…).

Jobs are scored against the track they belong to, the Role tracks page lists each track's best-matching jobs,
and tailoring / applying uses that track's resume.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Job, MatchAssessment, Resume, RoleTrack, User, to_dict
from ..security import audit, current_user, owned
from ..services.matching import latest_assessment, score_job
from ..services.roles import BY_KEY, FAMILIES, MAX_TRACKS, suggest_roles
from .profile import rescore_all
from .serialize import job_out

router = APIRouter(prefix="/api", tags=["role tracks"])
MAX_TITLES = 30  # job titles per track


class TrackIn(BaseModel):
    family: str = Field(default="custom", max_length=20)
    name: str = Field(default="", max_length=80)
    target_titles: list[str] = Field(default_factory=list, max_length=100)
    resume_id: Optional[int] = None

    @field_validator("family")
    @classmethod
    def _family(cls, v: str) -> str:
        if v != "custom" and v not in BY_KEY:
            raise ValueError("unknown role family")
        return v

    @field_validator("target_titles")
    @classmethod
    def _titles(cls, v: list[str]) -> list[str]:
        out = list(dict.fromkeys(t.strip()[:100] for t in v if t and t.strip()))
        return out


class TrackChoiceIn(BaseModel):
    track_id: Optional[int] = None  # None: let JobPilot pick the best-fitting track again


def _resume(db: Session, user: User, rid: Optional[int]) -> Optional[Resume]:
    return owned(db, Resume, rid, user) if rid else None


def _latest_by_job(db: Session, user_id: int) -> dict[int, tuple[int, Optional[int]]]:
    """job_id -> (score, track_id) of each job's newest assessment."""
    out: dict[int, tuple[int, Optional[int]]] = {}
    for jid, sc, tid in db.query(MatchAssessment.job_id, MatchAssessment.score, MatchAssessment.track_id) \
            .filter(MatchAssessment.user_id == user_id).order_by(MatchAssessment.id):
        out[jid] = (sc, tid)
    return out


def _visible_job_ids(db: Session, user_id: int) -> set[int]:
    return {jid for (jid,) in db.query(Job.id).filter(
        Job.user_id == user_id, Job.listing_status == "active", Job.duplicate_of_id.is_(None),
        or_(Job.triage.is_(None), Job.triage != "deleted"))}


def _track_out(t: RoleTrack, db: Session, latest: dict, visible: set[int]) -> dict:
    d = to_dict(t)
    r = db.get(Resume, t.resume_id) if t.resume_id else None
    d["resume"] = {"id": r.id, "filename": r.original_filename} if r else None
    fam = BY_KEY.get(t.family)
    d["family_name"] = fam.name if fam else "Custom"
    d["suggested_titles"] = [x for x in (fam.titles if fam else ()) if x not in (t.target_titles or [])][:8]
    d["searching_for"] = (t.target_titles or [])[:5] or list(fam.titles[:5] if fam else [t.name])
    scores = [sc for jid, (sc, tid) in latest.items() if tid == t.id and jid in visible]
    d["stats"] = {"jobs": len(scores), "strong": sum(1 for s in scores if s >= 70),
                  "average": round(sum(scores) / len(scores)) if scores else None}
    return d


@router.get("/roles")
def role_families(user: User = Depends(current_user)):
    """The role families you can build a track around, with their usual job titles."""
    return [{"key": f.key, "name": f.name, "titles": list(f.titles)} for f in FAMILIES]


@router.get("/tracks")
def list_tracks(user: User = Depends(current_user), db: Session = Depends(get_db)):
    tracks = db.query(RoleTrack).filter_by(user_id=user.id).order_by(RoleTrack.position, RoleTrack.id).all()
    latest, visible = _latest_by_job(db, user.id), _visible_job_ids(db, user.id)
    used = {t.resume_id: t.name for t in tracks if t.resume_id}
    resumes = [{"id": r.id, "filename": r.original_filename, "is_primary": r.is_primary,
                "created_at": r.created_at.isoformat() + "Z", "used_by": used.get(r.id),
                "suggested_roles": suggest_roles(r.text)}
               for r in db.query(Resume).filter_by(user_id=user.id).order_by(Resume.id.desc()).all()]
    unassigned = sum(1 for jid, (_, tid) in latest.items() if jid in visible and tid is None)
    return {"max": MAX_TRACKS, "max_titles": MAX_TITLES, "tracks": [_track_out(t, db, latest, visible) for t in tracks],
            "resumes": resumes, "unassigned_jobs": unassigned}


def _defaults(body: TrackIn) -> tuple[str, list[str]]:
    fam = BY_KEY.get(body.family)
    name = body.name.strip() or (fam.name if fam else "")
    if not name:
        raise HTTPException(400, "Give this track a name (e.g. 'Platform Engineer').")
    if len(body.target_titles) > MAX_TITLES:
        raise HTTPException(400, f"A track can have up to {MAX_TITLES} job titles (this one has {len(body.target_titles)}).")
    titles = body.target_titles or (list(fam.titles[:4]) if fam else [name])
    return name, titles


@router.post("/tracks")
def create_track(body: TrackIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = db.query(RoleTrack).filter_by(user_id=user.id).count()
    if n >= MAX_TRACKS:
        raise HTTPException(400, f"You can have up to {MAX_TRACKS} role tracks. Remove one to add another.")
    name, titles = _defaults(body)
    r = _resume(db, user, body.resume_id)
    if db.query(RoleTrack).filter(RoleTrack.user_id == user.id, func.lower(RoleTrack.name) == name.lower()).count():
        raise HTTPException(409, f"You already have a track called “{name}”.")
    pos = (db.query(func.max(RoleTrack.position)).filter(RoleTrack.user_id == user.id).scalar() or 0) + 1
    t = RoleTrack(user_id=user.id, name=name, family=body.family, target_titles=titles, resume_id=r.id if r else None,
                  position=pos)
    db.add(t)
    audit(db, user.id, "track.create", "role_track", None, name=name, family=body.family)
    db.commit()
    rescore_all(db, user.id)  # every job is re-assigned to its best-fitting track
    return _track_out(t, db, _latest_by_job(db, user.id), _visible_job_ids(db, user.id))


@router.put("/tracks/{tid}")
def update_track(tid: int, body: TrackIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, RoleTrack, tid, user)
    name, titles = _defaults(body)
    r = _resume(db, user, body.resume_id)
    t.name, t.family, t.target_titles, t.resume_id = name, body.family, titles, (r.id if r else None)
    audit(db, user.id, "track.update", "role_track", t.id, name=name)
    db.commit()
    rescore_all(db, user.id)
    return _track_out(t, db, _latest_by_job(db, user.id), _visible_job_ids(db, user.id))


@router.delete("/tracks/{tid}")
def delete_track(tid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, RoleTrack, tid, user)
    db.query(Job).filter(Job.user_id == user.id, Job.resume_track_id == t.id).update({"resume_track_id": None})
    db.delete(t)
    audit(db, user.id, "track.delete", "role_track", tid)
    db.commit()
    rescore_all(db, user.id)
    return {"ok": True}


@router.get("/tracks/{tid}/jobs")
def track_jobs(tid: int, limit: int = 10, min_score: int = 0,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    """This track's jobs, best ATS match first (jobs you haven't skipped or applied to)."""
    t = owned(db, RoleTrack, tid, user)
    latest, visible = _latest_by_job(db, user.id), _visible_job_ids(db, user.id)
    ids = [jid for jid, (sc, tr) in latest.items() if tr == t.id and jid in visible and sc >= min_score]
    jobs = {j.id: j for j in db.query(Job).filter(Job.id.in_(ids)).all()} if ids else {}
    open_ = [j for j in jobs.values() if j.application is None and j.triage != "skipped"]
    open_.sort(key=lambda j: -latest[j.id][0])
    page = open_[: max(1, min(limit, 50))]
    return {"total": len(open_), "items": [job_out(j, latest_assessment(db, j.id)) for j in page]}


@router.post("/jobs/{jid}/track")
def choose_track(jid: int, body: TrackChoiceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Use a specific role track's resume for this job (or let JobPilot choose again), and re-score it."""
    job = owned(db, Job, jid, user)
    if body.track_id is not None:
        owned(db, RoleTrack, body.track_id, user)
    job.resume_track_id = body.track_id
    m = score_job(db, job)
    db.commit()
    return {"track_id": m.track_id if m else None, "score": m.score if m else None,
            "track": (m.breakdown or {}).get("_track") if m else None}
