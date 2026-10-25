"""Discovery, matching and job detail endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import CandidateProfile, Job, JobSnapshot, JobSource, Resume, SavedSearch, User, to_dict
from ..schemas import ManualJobIn, SavedSearchIn, SourceIn
from ..security import audit, current_user, owned, rate_limit
from ..services import applications as appsvc
from ..services.discovery import describe_now, run_all_sources, run_source, upsert_job
from ..services.matching import assess, latest_assessment, score_job, score_jobs
from ..services.sources import ADAPTERS, NormalizedJob
from ..services.textutil import seniority_of, sha256
from .serialize import job_out

router = APIRouter(prefix="/api", tags=["jobs"])


# ---------------------------------------------------------------- sources


@router.get("/sources/catalog")
def catalog(user: User = Depends(current_user)):
    out = []
    for kind, cls in ADAPTERS.items():
        if (cls.is_simulated and not settings.allow_mock_sources) or cls.keyword:
            continue
        out.append({"kind": kind, "simulated": cls.is_simulated, "requires_credentials": cls.requires_credentials,
                    "docs_url": cls.docs_url,
                    "identifier_help": {
                        "greenhouse": "Board token from job-boards.greenhouse.io/<token> (e.g. 'anthropic', 'airbnb')",
                        "lever": "Site name from jobs.lever.co/<site> (e.g. 'palantir')",
                        "mock": "Any word — generates clearly-labelled SIMULATED demo listings",
                        "adzuna": "Use 'Find jobs for me' above instead", "remotive": "Use 'Find jobs for me' above instead",
                        "muse": "Use 'Find jobs for me' above instead",
                    }.get(kind, "")})
    return out


@router.get("/sources")
def list_sources(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [to_dict(s) for s in db.query(JobSource).filter_by(user_id=user.id).order_by(JobSource.id).all()]


@router.post("/sources")
def add_source(body: SourceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cls = ADAPTERS[body.kind]
    if cls.is_simulated and not settings.allow_mock_sources:
        raise HTTPException(400, "Simulated sources are disabled.")
    ident = body.identifier.strip().lower()
    if db.query(JobSource).filter_by(user_id=user.id, kind=body.kind, identifier=ident).first():
        raise HTTPException(409, "This source is already configured.")
    s = JobSource(user_id=user.id, kind=body.kind, identifier=ident, display_name=body.display_name,
                  is_simulated=cls.is_simulated)
    db.add(s)
    audit(db, user.id, "source.add", "job_source", None, kind=body.kind, identifier=ident)
    db.commit()
    return to_dict(s)


@router.patch("/sources/{sid}")
def toggle_source(sid: int, enabled: bool, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = owned(db, JobSource, sid, user)
    s.enabled = enabled
    db.commit()
    return to_dict(s)


@router.delete("/sources/{sid}")
def delete_source(sid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = owned(db, JobSource, sid, user)
    db.delete(s)  # jobs keep history; source_id becomes NULL
    db.commit()
    return {"ok": True}


@router.post("/sources/{sid}/run", dependencies=[Depends(rate_limit("discovery", 30, 3600))])
def run_one(sid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = owned(db, JobSource, sid, user)
    stats = run_source(db, s)
    if stats.get("changed_job_ids"):
        score_jobs(db, user.id, stats["changed_job_ids"])
    stats.pop("changed_job_ids", None)
    return stats


@router.post("/discovery/run", dependencies=[Depends(rate_limit("discovery", 30, 3600))])
def run_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = db.query(JobSource).filter_by(user_id=user.id, enabled=True).count()
    if n > 12:  # many company boards: run in the background so the page doesn't hang
        import threading

        from ..db import session_scope
        from ..scheduler import user_lock

        lock = user_lock(user.id)
        if not lock.acquire(blocking=False):
            return {"started": False, "running": True, "results": [], "sources": n}

        def work(uid=user.id):
            try:
                with session_scope() as bg:
                    run_all_sources(bg, uid)
            finally:
                lock.release()

        threading.Thread(target=work, daemon=True).start()
        return {"started": True, "results": [], "sources": n}
    results = run_all_sources(db, user.id)
    for r in results:
        r.pop("changed_job_ids", None)
    return {"results": results}


# ---------------------------------------------------------------- jobs


@router.get("/jobs")
def list_jobs(
    q: str = "", location: str = "", company: str = "", remote: str = "", seniority: str = "",
    min_score: int = 0, max_score: Optional[int] = None, posted_within: int = Query(0, ge=0, le=24 * 365),
    qualified_only: bool = True,
    salary_min: Optional[float] = None, status: str = "active", source: str = "",
    pipeline: str = "", include_duplicates: bool = False, include_simulated: bool = True,
    sort: str = "score", limit: int = Query(100, le=500), offset: int = 0,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    from sqlalchemy import func
    from sqlalchemy.orm import defer, selectinload

    from ..models import MatchAssessment

    # don't load every description (thousands of jobs × several KB) just to list 100 of them
    qry = db.query(Job).options(defer(Job.description_text), defer(Job.content_hash), selectinload(Job.application)) \
        .filter(Job.user_id == user.id)
    if status in ("active", "closed"):
        qry = qry.filter(Job.listing_status == status)
    if not include_duplicates:
        qry = qry.filter(Job.duplicate_of_id.is_(None))
    if not include_simulated:
        qry = qry.filter(Job.is_simulated.is_(False))
    if q:
        like = f"%{q.lower()}%"
        from sqlalchemy import func

        qry = qry.filter(or_(func.lower(Job.title).like(like), func.lower(Job.description_text).like(like),
                             func.lower(Job.company).like(like)))
    if location:
        qry = qry.filter(Job.location.ilike(f"%{location}%"))
    if company:
        qry = qry.filter(Job.company.ilike(f"%{company}%"))
    if remote:
        qry = qry.filter(Job.remote_type.in_(remote.split(",")))
    if source:
        qry = qry.filter(Job.source_kind == source)
    if salary_min:
        qry = qry.filter(or_(Job.salary_max >= salary_min, Job.salary_max.is_(None)))
    jobs = qry.all()
    latest: dict[int, tuple[int, int, Optional[str]]] = {}  # job_id -> (assessment id, score, education fit), newest wins
    for jid_, aid, sc, edu in db.query(MatchAssessment.job_id, MatchAssessment.id, MatchAssessment.score, MatchAssessment.edu_status) \
            .filter(MatchAssessment.user_id == user.id).order_by(MatchAssessment.id):
        latest[jid_] = (aid, sc, edu)
    if posted_within:
        from datetime import timedelta

        from ..models import utcnow

        since = utcnow() - timedelta(hours=posted_within)
        jobs = [j for j in jobs if (j.posted_at or j.discovered_at) >= since]
    hidden = 0
    if qualified_only:  # hide roles that require a higher degree than yours (e.g. PhD-only for a master's)
        before = len(jobs)
        jobs = [j for j in jobs if not (j.id in latest and latest[j.id][2] == "below")]
        hidden = before - len(jobs)

    class _S:  # lightweight stand-in with .score for filtering/sorting
        __slots__ = ("score",)

        def __init__(self, score):
            self.score = score

    scores = {k: _S(v[1]) for k, v in latest.items()}
    if seniority:
        from ..services.textutil import SENIORITY_LEVELS

        want = {SENIORITY_LEVELS.get(s.strip().lower()) for s in seniority.split(",")}
        jobs = [j for j in jobs if seniority_of(j.title) in want]
    if min_score:
        jobs = [j for j in jobs if j.id in scores and scores[j.id].score >= min_score]
    if max_score is not None and max_score < 100:
        jobs = [j for j in jobs if j.id in scores and scores[j.id].score <= max_score]
    if pipeline:
        want_p = set(pipeline.split(","))
        jobs = [j for j in jobs if (j.application.status if j.application else "discovered") in want_p]
    keyf = {
        "score": lambda j: -(scores[j.id].score if j.id in scores else -1),
        "posted": lambda j: -((j.posted_at or j.discovered_at).timestamp()),
        "score_asc": lambda j: (scores[j.id].score if j.id in scores else 999),
        "discovered": lambda j: -j.discovered_at.timestamp(),
        "company": lambda j: j.company.lower(),
        "salary": lambda j: -(j.salary_max or j.salary_min or 0),
    }.get(sort, lambda j: -j.discovered_at.timestamp())
    jobs.sort(key=keyf)
    total = len(jobs)
    page = jobs[offset: offset + limit]
    ids = [j.id for j in page]
    full = {m.job_id: m for m in db.query(MatchAssessment).filter(
        MatchAssessment.id.in_([latest[i][0] for i in ids if i in latest]))} if ids else {}
    snips = dict(db.query(Job.id, func.substr(Job.description_text, 1, 220)).filter(Job.id.in_(ids)).all()) if ids else {}
    return {"total": total, "hidden_higher_degree": hidden,
            "items": [job_out(j, full.get(j.id), snippet=snips.get(j.id) or "") for j in page]}


@router.get("/jobs/{jid}")
def job_detail(jid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = owned(db, Job, jid, user)
    profile = db.query(CandidateProfile).filter_by(user_id=user.id).one_or_none()
    # fill in the full description from the source if we only have a summary, then (re)score
    changed = describe_now(db, job)
    m = latest_assessment(db, job.id)
    if profile is not None and (changed or m is None):
        score_job(db, job, profile)
        db.commit()
        m = latest_assessment(db, job.id)
    resume = db.query(Resume).filter_by(user_id=user.id, is_primary=True).one_or_none()
    live = assess(job, profile, resume.text if resume else "") if profile else None
    out = job_out(job, m, full=True)
    out["relevant_experience"] = live["relevant_experience"] if live else []
    out["years_experience"] = live["years_experience"] if live else None
    out["history"] = [{"captured_at": s.captured_at.isoformat() + "Z", "hash": s.content_hash[:10]}
                      for s in db.query(JobSnapshot).filter_by(job_id=job.id).order_by(JobSnapshot.id).all()]
    out["duplicates"] = [{"id": d.id, "source_kind": d.source_kind, "url": d.url}
                         for d in db.query(Job).filter_by(user_id=user.id, duplicate_of_id=job.id).all()]
    out["source"] = to_dict(db.get(JobSource, job.source_id)) if job.source_id and db.get(JobSource, job.source_id) else None
    docs = []
    from ..models import Document

    for d in db.query(Document).filter_by(job_id=job.id).order_by(Document.kind, Document.version.desc()).all():
        docs.append({"id": d.id, "kind": d.kind, "version": d.version, "status": d.status,
                     "created_at": d.created_at.isoformat() + "Z", "generator": d.generator})
    out["documents"] = docs
    return out


@router.post("/jobs/manual")
def add_manual(body: ManualJobIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Add a job you found elsewhere (e.g. a company site). Marked as manual."""
    ext = "manual-" + sha256(body.company, body.title, body.url or body.location)[:16]
    n = NormalizedJob(external_id=ext, title=body.title, company=body.company, location=body.location,
                      remote_type=body.remote_type, description_text=body.description_text,
                      salary_min=body.salary_min, salary_max=body.salary_max,
                      salary_currency="USD" if body.salary_min else "", salary_interval="per-year-salary" if body.salary_min else "",
                      url=body.url, apply_url=body.url)
    job, state = upsert_job(db, user.id, None, n, "manual", False)
    job.is_manual = True
    db.commit()
    score_job(db, job)
    db.commit()
    return {"job": job_out(job, latest_assessment(db, job.id)), "state": state}


@router.post("/jobs/{jid}/rescore")
def rescore(jid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = owned(db, Job, jid, user)
    m = score_job(db, job)
    db.commit()
    if m is None:
        raise HTTPException(400, "Create your profile first.")
    return to_dict(m)


@router.post("/jobs/{jid}/shortlist")
def shortlist(jid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = owned(db, Job, jid, user)
    app = appsvc.get_or_create(db, job)
    db.commit()
    return {"application_id": app.id, "status": app.status}


@router.delete("/jobs/{jid}")
def delete_job(jid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = owned(db, Job, jid, user)
    if job.application and job.application.submitted_at:
        raise HTTPException(400, "This job has a submitted application; withdraw it instead of deleting history.")
    db.query(Job).filter_by(duplicate_of_id=job.id).update({"duplicate_of_id": None})
    db.delete(job)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- saved searches


@router.get("/saved-searches")
def saved(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [to_dict(s) for s in db.query(SavedSearch).filter_by(user_id=user.id).all()]


@router.post("/saved-searches")
def save_search(body: SavedSearchIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    allowed = {"q", "location", "company", "remote", "seniority", "min_score", "salary_min", "status", "source", "sort"}
    s = SavedSearch(user_id=user.id, name=body.name, filters={k: v for k, v in body.filters.items() if k in allowed})
    db.add(s)
    db.commit()
    return to_dict(s)


@router.delete("/saved-searches/{sid}")
def del_search(sid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(owned(db, SavedSearch, sid, user))
    db.commit()
    return {"ok": True}
