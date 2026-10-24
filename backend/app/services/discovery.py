"""Job Discovery Agent: runs source adapters, upserts, dedupes, tracks history."""
from __future__ import annotations

import logging
import time
from dataclasses import asdict
from datetime import timedelta
from typing import Optional

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Job, JobSnapshot, JobSource, utcnow
from ..security import audit
from .sources import ADAPTERS, COMPANY_KINDS, NormalizedJob, SourceError
from .sources.base import JobSourceAdapter
from .sources.keyword import title_matches
from .textutil import job_fingerprint, sha256

log = logging.getLogger("jobpilot.discovery")

_TRACKED = ("title", "location", "description_text", "salary_min", "salary_max", "remote_type", "apply_url")


def _content_hash(n: NormalizedJob) -> str:
    return sha256(*[str(getattr(n, f) or "") for f in _TRACKED])


def upsert_job(db: Session, user_id: int, source: Optional[JobSource], n: NormalizedJob,
               kind: str, simulated: bool) -> tuple[Job, str]:
    """Insert or update one listing. Returns (job, 'new'|'updated'|'unchanged')."""
    now = utcnow()
    chash = _content_hash(n)
    job = (
        db.query(Job)
        .filter(Job.user_id == user_id, Job.source_kind == kind, Job.external_id == n.external_id)
        .one_or_none()
    )
    data = asdict(n)
    data.pop("raw", None)
    if job is None:
        job = Job(user_id=user_id, source_id=source.id if source else None, source_kind=kind,
                  is_simulated=simulated, fingerprint=job_fingerprint(n.company, n.title, n.location),
                  content_hash=chash, discovered_at=now, last_checked_at=now, **data)
        db.add(job)
        db.flush()
        db.add(JobSnapshot(job_id=job.id, content_hash=chash, data=_jsonable(data)))
        _mark_duplicate(db, job)
        return job, "new"
    if len(n.description_text or "") < 200 and len(job.description_text or "") > len(n.description_text or ""):
        # this run only got a summary; keep the full description fetched earlier (or pasted by the user)
        n.description_text = job.description_text
        chash = _content_hash(n)
        data["description_text"] = n.description_text
    job.last_checked_at = now
    state = "unchanged"
    if job.listing_status != "active":
        job.listing_status = "active"
        state = "updated"
    if job.content_hash != chash:
        for k, v in data.items():
            setattr(job, k, v)
        job.content_hash = chash
        job.fingerprint = job_fingerprint(n.company, n.title, n.location)
        db.add(JobSnapshot(job_id=job.id, content_hash=chash, data=_jsonable(data)))
        state = "updated"
    return job, state


def _jsonable(d: dict) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in d.items()}


def _mark_duplicate(db: Session, job: Job) -> None:
    original = (
        db.query(Job)
        .filter(Job.user_id == job.user_id, Job.fingerprint == job.fingerprint, Job.id != job.id,
                Job.duplicate_of_id.is_(None))
        .order_by(Job.id)
        .first()
    )
    if original is not None:
        job.duplicate_of_id = original.id


def run_source(db: Session, source: JobSource, *, transport: Optional[httpx.BaseTransport] = None) -> dict:
    adapter_cls = ADAPTERS.get(source.kind)
    if adapter_cls is None:
        raise SourceError(f"Unknown source kind: {source.kind}")
    if adapter_cls.is_simulated and not settings.allow_mock_sources:
        raise SourceError("Simulated sources are disabled (JOBPILOT_ALLOW_MOCK_SOURCES=0).")
    stats = {"source_id": source.id, "kind": source.kind, "new": 0, "updated": 0, "unchanged": 0,
             "closed": 0, "error": None, "simulated": adapter_cls.is_simulated}
    interval = adapter_cls.interval_for(source.identifier)
    if interval and source.last_run_at and source.last_status == "ok" and \
            utcnow() - source.last_run_at < timedelta(hours=interval):
        stats["skipped"] = f"{source.kind}: searched recently — it's checked at most once every {interval}h."
        return stats
    context = search_context(db, source.user_id) if (adapter_cls.keyword or source.kind in COMPANY_KINDS) else None
    adapter = adapter_cls(source.identifier, transport=transport, context=context if adapter_cls.keyword else None)
    # company boards list every opening; keep only roles matching the user's target titles
    queries = (context or {}).get("queries", []) if source.kind in COMPANY_KINDS else []
    keep = (lambda t: title_matches(t, queries)) if queries else None
    if keep and hasattr(adapter, "title_filter"):
        adapter.title_filter = keep
    if hasattr(adapter, "queries") and not adapter_cls.keyword:
        adapter.queries = queries  # Workday: search the site for the target titles
    adapter.known_described = frozenset(eid for (eid,) in db.query(Job.external_id).filter(
        Job.user_id == source.user_id, Job.source_kind == source.kind, Job.source_id == source.id,
        func.length(Job.description_text) >= 200))
    source.last_run_at = utcnow()
    try:
        listings = adapter.fetch()
    except SourceError as e:
        source.last_status, source.last_error = "error", str(e)
        stats["error"] = str(e)
        audit(db, source.user_id, "discovery.error", "job_source", source.id, error=str(e))
        db.commit()
        return stats
    if source.kind in ("ashby", "lever", "recruitee", "workday", "eightfold", "oraclehcm") and source.display_name and source.display_name != source.identifier:
        for n in listings:  # these feeds don't carry a proper company name
            n.company = source.display_name
    seen: set[str] = {n.external_id for n in listings}  # everything still on the board (for closed detection)
    new_ids: list[int] = []
    stats["on_board"] = len(listings)
    if keep:
        listings = [n for n in listings if keep(n.title)]
    stats["matching"] = len(listings)
    for n in listings:
        job, state = upsert_job(db, source.user_id, source, n, source.kind, adapter_cls.is_simulated)
        stats[state] += 1
        if state in ("new", "updated"):
            new_ids.append(job.id)
    # A company board's own listing is authoritative: anything missing is no longer posted.
    # (Keyword searches return a changing subset, so absence there means nothing.)
    closable = [] if (adapter_cls.keyword or getattr(adapter_cls, "partial", False)) else db.query(Job).filter(
        Job.user_id == source.user_id, Job.source_id == source.id, Job.listing_status == "active").all()
    for job in closable:
        if job.external_id not in seen:
            job.listing_status = "closed"
            job.last_checked_at = utcnow()
            stats["closed"] += 1
    new_ids += backfill_descriptions(db, source, adapter)
    source.last_status, source.last_error, source.last_job_count = "ok", "", len(listings)
    if not source.display_name and listings:
        source.display_name = listings[0].company
    audit(db, source.user_id, "discovery.run", "job_source", source.id,
          **{k: v for k, v in stats.items() if k in ("new", "updated", "closed")})
    db.commit()
    stats["changed_job_ids"] = new_ids
    return stats


def search_queries(profile, resume_text: str = "") -> list[str]:
    prefs = (profile.preferences or {}) if profile else {}
    qs = [t.strip() for t in prefs.get("target_titles") or [] if t.strip()]
    if not qs and profile:
        if profile.headline and len(profile.headline) < 60:
            qs.append(profile.headline)
        for e in profile.experience or []:
            if e.get("title") and e["title"] not in qs:
                qs.append(e["title"])
    return list(dict.fromkeys(qs))[:3]


def search_context(db: Session, user_id: int) -> dict:
    from ..models import CandidateProfile, IntegrationSetting
    from .secretbox import unseal

    profile = db.query(CandidateProfile).filter_by(user_id=user_id).one_or_none()
    prefs = (profile.preferences or {}) if profile else {}
    creds: dict = {}
    for row in db.query(IntegrationSetting).filter_by(user_id=user_id).all():
        if row.provider != "ai":  # provider fields use distinct names (app_id, rapidapi_key, usajobs_key, …)
            creds.update(unseal(row.data_encrypted))
    locations = [l for l in prefs.get("locations") or [] if l.strip()]
    return {"queries": search_queries(profile), "locations": locations, "credentials": creds}


MIN_DESC = 200  # shorter than this is a summary, not a job description


def backfill_descriptions(db: Session, source: JobSource, adapter, limit: int = 40) -> list[int]:
    """Fetch full descriptions for this source's saved jobs that only have a summary."""
    if type(adapter).describe is JobSourceAdapter.describe:
        return []
    jobs = db.query(Job).filter(Job.source_id == source.id, Job.listing_status == "active",
                                func.length(Job.description_text) < MIN_DESC).order_by(Job.discovered_at.desc()).limit(limit).all()
    done = []
    for i, job in enumerate(jobs):
        if i:
            adapter._sleep(0.3)
        try:
            desc = adapter.describe(job.external_id, job.url or job.apply_url or "")
        except SourceError:
            continue
        except Exception:  # noqa: BLE001 - one odd page mustn't fail the run
            log.exception("describe failed for job %s", job.id)
            continue
        if desc and len(desc) > len(job.description_text or ""):
            job.description_text = desc
            done.append(job.id)
    return done


def describe_now(db: Session, job: Job) -> bool:
    """Fetch a job's full description on demand (when the user opens it). Returns True if it changed."""
    if job.is_manual or len(job.description_text or "") >= MIN_DESC:
        return False
    src = db.get(JobSource, job.source_id) if job.source_id else None
    cls = ADAPTERS.get(job.source_kind)
    if cls is None or cls.describe is JobSourceAdapter.describe or cls.is_simulated:
        return False
    try:
        adapter = cls(src.identifier if src else "auto", context=None if not cls.keyword else {"queries": [], "locations": [], "credentials": {}})
        adapter.timeout_s = 15
        desc = adapter.describe(job.external_id, job.url or job.apply_url or "")
    except Exception:  # noqa: BLE001
        return False
    if desc and len(desc) > len(job.description_text or ""):
        job.description_text = desc
        db.commit()
        return True
    return False


def pause_between_sources() -> None:
    """Give web requests a turn: on a small (0.1 CPU) server a long search run otherwise starves the site."""
    if settings.source_pause_s:
        time.sleep(settings.source_pause_s)


def run_all_sources(db: Session, user_id: int) -> list[dict]:
    from .matching import score_jobs  # local import to avoid cycle

    results = []
    for i, src in enumerate(db.query(JobSource).filter(JobSource.user_id == user_id, JobSource.enabled.is_(True)).all()):
        if i:
            pause_between_sources()
        r = run_source(db, src)
        results.append(r)
        if r.get("changed_job_ids"):  # score as we go, so an interrupted run still leaves scored jobs
            score_jobs(db, user_id, r["changed_job_ids"])
    score_unscored(db, user_id)
    return results


def score_unscored(db: Session, user_id: int, limit: int = 500) -> int:
    """Score jobs that never got an ATS score (e.g. a run was cut off by a restart)."""
    from ..models import MatchAssessment
    from .matching import score_jobs

    scored = db.query(MatchAssessment.job_id).filter(MatchAssessment.user_id == user_id)
    ids = [jid for (jid,) in db.query(Job.id).filter(Job.user_id == user_id, Job.duplicate_of_id.is_(None),
                                                      ~Job.id.in_(scored)).limit(limit)]
    return score_jobs(db, user_id, ids) if ids else 0
