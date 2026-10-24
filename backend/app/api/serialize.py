"""Response shaping helpers."""
from __future__ import annotations

from typing import Optional

from ..models import Application, Document, Job, MatchAssessment, to_dict


def job_out(job: Job, m: Optional[MatchAssessment] = None, full: bool = False, snippet: Optional[str] = None) -> dict:
    d = to_dict(job, exclude=() if full else ("description_text", "content_hash"))
    if not full:
        d["snippet"] = snippet if snippet is not None else (job.description_text or "")[:220]
    d["match"] = match_out(m) if m else None
    d["application"] = (
        {"id": job.application.id, "status": job.application.status} if job.application is not None else None
    )
    d["pipeline_status"] = job.application.status if job.application is not None else "discovered"
    return d


def match_out(m: MatchAssessment) -> dict:
    return to_dict(m)


def doc_out(d: Document) -> dict:
    return to_dict(d)


def app_out(a: Application, m: Optional[MatchAssessment] = None) -> dict:
    d = to_dict(a)
    j = a.job
    d["job"] = {"id": j.id, "title": j.title, "company": j.company, "location": j.location, "url": j.url,
                "apply_url": j.apply_url, "source_kind": j.source_kind, "is_simulated": j.is_simulated,
                "listing_status": j.listing_status, "salary_min": j.salary_min, "salary_max": j.salary_max,
                "salary_currency": j.salary_currency, "remote_type": j.remote_type}
    d["match_score"] = m.score if m else None
    return d
