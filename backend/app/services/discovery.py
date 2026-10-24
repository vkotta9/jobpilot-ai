"""Job Discovery Agent: runs source adapters, upserts, dedupes, tracks history."""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Job, JobSnapshot, JobSource, utcnow
from ..security import audit
from .sources import ADAPTERS, NormalizedJob, SourceError
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
    if adapter_cls.min_interval_hours and source.last_run_at and source.last_status == "ok" and \
            utcnow() - source.last_run_at < timedelta(hours=adapter_cls.min_interval_hours):
        stats["skipped"] = f"{source.kind} allows only a few searches per day — next run after " \
                           f"{adapter_cls.min_interval_hours}h."
        return stats
    context = search_context(db, source.user_id) if adapter_cls.keyword else None
    adapter = adapter_cls(source.identifier, transport=transport, context=context)
    source.last_run_at = utcnow()
    try:
        listings = adapter.fetch()
    except SourceError as e:
        source.last_status, source.last_error = "error", str(e)
        stats["error"] = str(e)
        audit(db, source.user_id, "discovery.error", "job_source", source.id, error=str(e))
        db.commit()
        return stats
    seen: set[str] = set()
    new_ids: list[int] = []
    for n in listings:
        job, state = upsert_job(db, source.user_id, source, n, source.kind, adapter_cls.is_simulated)
        seen.add(n.external_id)
        stats[state] += 1
        if state in ("new", "updated"):
            new_ids.append(job.id)
    # A company board's own listing is authoritative: anything missing is no longer posted.
    # (Keyword searches return a changing subset, so absence there means nothing.)
    closable = [] if adapter_cls.keyword else db.query(Job).filter(
        Job.user_id == source.user_id, Job.source_id == source.id, Job.listing_status == "active").all()
    for job in closable:
        if job.external_id not in seen:
            job.listing_status = "closed"
            job.last_checked_at = utcnow()
            stats["closed"] += 1
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
    creds = {}
    for row in db.query(IntegrationSetting).filter_by(user_id=user_id).all():
        creds[row.provider] = unseal(row.data_encrypted)
    locations = [l for l in prefs.get("locations") or [] if l.strip()]
    return {"queries": search_queries(profile), "locations": locations,
            "credentials": {**creds.get("adzuna", {}), **({"api_key": creds["muse"].get("api_key")} if creds.get("muse") else {})}}


def run_all_sources(db: Session, user_id: int) -> list[dict]:
    from .matching import score_jobs  # local import to avoid cycle

    results = []
    for src in db.query(JobSource).filter(JobSource.user_id == user_id, JobSource.enabled.is_(True)).all():
        results.append(run_source(db, src))
    changed = [jid for r in results for jid in r.get("changed_job_ids", [])]
    if changed:
        score_jobs(db, user_id, changed)
    return results
