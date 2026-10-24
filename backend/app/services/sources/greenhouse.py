"""Greenhouse Job Board API (public, read-only, no credentials).

GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
The board token is the slug in a company's Greenhouse board URL, e.g.
https://job-boards.greenhouse.io/<board_token>.
Submitting applications via this API requires the *employer's* Job Board API
key, so candidates cannot use it; JobPilot uses guided manual submission.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..textutil import strip_html
from .base import JobSourceAdapter, NormalizedJob, SourceError, infer_remote_type

API = "https://boards-api.greenhouse.io/v1/boards/{token}"


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


class GreenhouseAdapter(JobSourceAdapter):
    kind = "greenhouse"
    docs_url = "https://developers.greenhouse.io/job-board.html"

    def fetch(self) -> list[NormalizedJob]:
        company = self._board_name()
        data = self._get_json(API.format(token=self.identifier) + "/jobs", params={"content": "true"})
        if not isinstance(data, dict) or "jobs" not in data:
            raise SourceError("greenhouse: response missing 'jobs'")
        return [self.normalize(j, company) for j in data.get("jobs") or [] if j.get("id") and j.get("title")]

    def _board_name(self) -> str:
        try:
            meta = self._get_json(API.format(token=self.identifier), max_attempts=1)
            if isinstance(meta, dict) and meta.get("name"):
                return str(meta["name"])
        except SourceError as e:
            if e.status == 404:
                raise
        return self.company_name()

    @staticmethod
    def normalize(j: dict, company: str) -> NormalizedJob:
        loc = (j.get("location") or {}).get("name", "") if isinstance(j.get("location"), dict) else ""
        desc = strip_html(j.get("content") or "")
        depts = ", ".join(d.get("name", "") for d in (j.get("departments") or []) if d.get("name"))
        emp_type = ""
        for m in j.get("metadata") or []:
            if isinstance(m, dict) and "employment" in str(m.get("name", "")).lower() and m.get("value"):
                emp_type = str(m["value"])
        url = j.get("absolute_url") or ""
        return NormalizedJob(
            external_id=str(j["id"]),
            title=str(j["title"]).strip(),
            company=company,
            location=loc,
            remote_type=infer_remote_type(loc, j.get("title", "")),
            employment_type=emp_type,
            department=depts,
            description_text=desc,
            posted_at=_parse_dt(j.get("first_published")) or _parse_dt(j.get("updated_at")),
            url=url,
            apply_url=url,  # Greenhouse hosts the form on the same page
            raw={k: j.get(k) for k in ("id", "internal_job_id", "updated_at", "requisition_id")},
        )
