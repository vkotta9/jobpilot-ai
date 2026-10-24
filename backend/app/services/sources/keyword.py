"""Keyword job-search sources driven by the user's profile (no company list needed).

* Adzuna  — broad US job search aggregator; free developer key (app_id + app_key).
            Returns a description *snippet* only; JobPilot flags this and lets the
            user paste the full description for an accurate score.
* Remotive — remote jobs, no key. Their terms: at most a few requests per day,
            link back to Remotive and credit them (JobPilot shows "via Remotive").
* The Muse — no key needed for light use; no keyword parameter, so JobPilot pulls
            the newest postings for the user's locations and keeps title matches.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from ..textutil import STOPWORDS, strip_html
from .base import JobSourceAdapter, NormalizedJob, SourceError, infer_remote_type

NOISE = {"senior", "sr", "junior", "jr", "staff", "lead", "principal", "ii", "iii", "i", "associate", "entry", "level",
         "remote", "hybrid", "intern", "new", "grad", "graduate"}


def core_words(q: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9+#.]+", q.lower()) if w not in NOISE and w not in STOPWORDS]


def title_matches(title: str, queries: list[str]) -> bool:
    t = set(re.findall(r"[a-z0-9+#.]+", title.lower()))
    for q in queries:
        words = core_words(q)
        need = len(words) if len(words) <= 2 else len(words) - 1  # "software engineer" needs both words
        if words and sum(w in t or (w.endswith("s") and w[:-1] in t) for w in words) >= need:
            return True
    return False


def _dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


class KeywordAdapter(JobSourceAdapter):
    keyword = True

    def __init__(self, identifier: str, *, context: Optional[dict] = None, **kw):
        super().__init__(identifier, **kw)
        ctx = context or {}
        self.queries: list[str] = [q for q in ctx.get("queries", []) if q.strip()][:3]
        self.locations: list[str] = ctx.get("locations", [])[:2]
        self.credentials: dict = ctx.get("credentials", {}) or {}

    def _need_queries(self):
        if not self.queries:
            raise SourceError(f"{self.kind}: add target job titles in your Profile so JobPilot knows what to search for.")


class AdzunaAdapter(KeywordAdapter):
    kind = "adzuna"
    requires_credentials = True
    docs_url = "https://developer.adzuna.com/"
    label = "Adzuna (all US job boards)"

    def fetch(self) -> list[NormalizedJob]:
        self._need_queries()
        app_id, app_key = self.credentials.get("app_id"), self.credentials.get("app_key")
        if not app_id or not app_key:
            raise SourceError("adzuna: connect your free Adzuna key in Settings → Connections.")
        country = (self.credentials.get("country") or "us").lower()
        where_list = [l for l in self.locations if l.lower() not in ("remote", "anywhere")] or [""]
        out: dict[str, NormalizedJob] = {}
        for q in self.queries:
            for where in where_list[:2]:
                params = {"app_id": app_id, "app_key": app_key, "what": q, "results_per_page": 50,
                          "max_days_old": 21, "sort_by": "date", "content-type": "application/json"}
                if where:
                    params["where"] = where
                try:
                    data = self._get_json(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", params=params)
                except SourceError as e:
                    if e.status in (401, 403):
                        raise SourceError("adzuna: the app_id/app_key were rejected. Check them in Settings → Connections.")
                    raise
                for r in (data or {}).get("results", []):
                    n = self.normalize(r)
                    if n and n.external_id not in out:
                        out[n.external_id] = n
        return list(out.values())

    @staticmethod
    def normalize(r: dict) -> Optional[NormalizedJob]:
        if not r.get("id") or not r.get("title"):
            return None
        predicted = str(r.get("salary_is_predicted", "0")) == "1"
        loc = (r.get("location") or {}).get("display_name", "")
        title = strip_html(r.get("title", ""))
        return NormalizedJob(
            external_id=str(r["id"]), title=title, company=(r.get("company") or {}).get("display_name", "") or "Unknown",
            location=loc, remote_type=infer_remote_type(loc, title, r.get("description", "")),
            employment_type=(r.get("contract_time") or "").replace("_", " "),
            department=(r.get("category") or {}).get("label", ""),
            description_text=strip_html(r.get("description", "")),
            salary_min=None if predicted else r.get("salary_min"), salary_max=None if predicted else r.get("salary_max"),
            salary_currency="USD" if r.get("salary_min") and not predicted else "",
            salary_interval="per-year-salary" if r.get("salary_min") and not predicted else "",
            posted_at=_dt(r.get("created")), url=r.get("redirect_url", ""), apply_url=r.get("redirect_url", ""),
        )


class RemotiveAdapter(KeywordAdapter):
    kind = "remotive"
    docs_url = "https://github.com/remotive-com/remote-jobs-api"
    label = "Remotive (remote jobs)"
    min_interval_hours = 6  # their terms: only a few requests per day

    def fetch(self) -> list[NormalizedJob]:
        self._need_queries()
        out: dict[str, NormalizedJob] = {}
        for q in self.queries[:2]:
            data = self._get_json("https://remotive.com/api/remote-jobs", params={"search": q, "limit": 60}, max_attempts=1)
            for j in (data or {}).get("jobs", []):
                if not title_matches(j.get("title", ""), self.queries):
                    continue
                n = self.normalize(j)
                if n:
                    out[n.external_id] = n
        return list(out.values())

    @staticmethod
    def normalize(j: dict) -> Optional[NormalizedJob]:
        if not j.get("id") or not j.get("title"):
            return None
        desc = strip_html(j.get("description", ""))
        if j.get("salary"):
            desc = f"Salary (as listed): {j['salary']}\n\n{desc}"
        return NormalizedJob(
            external_id=str(j["id"]), title=j["title"].strip(), company=j.get("company_name", "") or "Unknown",
            location=("Remote — " + j["candidate_required_location"]) if j.get("candidate_required_location") else "Remote",
            remote_type="remote", employment_type=(j.get("job_type") or "").replace("_", " "),
            department=j.get("category", ""), description_text=desc + "\n\n(Listing via Remotive)",
            posted_at=_dt(j.get("publication_date")), url=j.get("url", ""), apply_url=j.get("url", ""),
        )


class MuseAdapter(KeywordAdapter):
    kind = "muse"
    docs_url = "https://www.themuse.com/developers/api/v2"
    label = "The Muse"

    def fetch(self) -> list[NormalizedJob]:
        self._need_queries()
        locs = [l for l in self.locations if l] + ["Flexible / Remote"]
        out: dict[str, NormalizedJob] = {}
        for loc in locs[:3]:
            for page in range(0, 5):
                params = {"page": page, "descending": "true", "location": loc}
                if self.credentials.get("api_key"):
                    params["api_key"] = self.credentials["api_key"]
                data = self._get_json("https://www.themuse.com/api/public/jobs", params=params, max_attempts=2)
                results = (data or {}).get("results", [])
                for j in results:
                    if title_matches(j.get("name", ""), self.queries):
                        n = self.normalize(j)
                        if n:
                            out[n.external_id] = n
                if not results or page + 1 >= int((data or {}).get("page_count", 1)):
                    break
        return list(out.values())

    @staticmethod
    def normalize(j: dict) -> Optional[NormalizedJob]:
        if not j.get("id") or not j.get("name"):
            return None
        locs = ", ".join(l.get("name", "") for l in j.get("locations") or [] if l.get("name"))
        url = (j.get("refs") or {}).get("landing_page", "")
        return NormalizedJob(
            external_id=str(j["id"]), title=j["name"].strip(), company=(j.get("company") or {}).get("name", "") or "Unknown",
            location=locs, remote_type=infer_remote_type(locs), employment_type=j.get("type", "") or "",
            department=", ".join(c.get("name", "") for c in j.get("categories") or []),
            description_text=strip_html(j.get("contents", "")), posted_at=_dt(j.get("publication_date")),
            url=url, apply_url=url,
        )
