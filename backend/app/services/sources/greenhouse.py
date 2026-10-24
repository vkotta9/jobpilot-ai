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
    DETAIL_MAX = 40  # more matching roles than this: one bulk download is cheaper than many requests

    def fetch(self) -> list[NormalizedJob]:
        company = self._board_name()
        base = API.format(token=self.identifier) + "/jobs"
        if self.title_filter is not None:
            # Big boards (SpaceX lists ~2,800 roles) are slow to download with descriptions. List titles
            # first, then fetch descriptions only for roles matching the user's target titles.
            data = self._get_json(base)
            if not isinstance(data, dict) or "jobs" not in data:
                raise SourceError("greenhouse: response missing 'jobs'")
            jobs = [j for j in data.get("jobs") or [] if j.get("id") and j.get("title")]
            wanted = [j for j in jobs if not self._skip_detail(j["title"])]
            if len(wanted) <= self.DETAIL_MAX:
                detail = {}
                for j in wanted:
                    try:
                        d = self._get_json(f"{base}/{j['id']}", max_attempts=2)
                        if isinstance(d, dict) and d.get("id") and d.get("title"):
                            detail[j["id"]] = d
                    except SourceError:
                        pass
                return [self.normalize(detail.get(j["id"], j), company) for j in jobs]
        data = self._get_json(base, params={"content": "true"})
        if not isinstance(data, dict) or "jobs" not in data:
            raise SourceError("greenhouse: response missing 'jobs'")
        return [self.normalize(self._lite(j, "title", ("content",)), company) for j in data.get("jobs") or [] if j.get("id") and j.get("title")]

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
