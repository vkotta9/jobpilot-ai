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
from datetime import datetime, timezone
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


def _unix(ts) -> Optional[datetime]:
    try:
        v = float(ts)
        if v > 1e12:
            v /= 1000
        return datetime.fromtimestamp(v, tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        return _dt(ts) if isinstance(ts, str) else None


class ArbeitnowAdapter(KeywordAdapter):
    """Free, no key. Mostly Europe (Germany); useful if you're open to EU roles / visa sponsorship."""

    kind = "arbeitnow"
    docs_url = "https://www.arbeitnow.com/blog/job-board-api"
    label = "Arbeitnow (Europe, visa-friendly)"

    def fetch(self) -> list[NormalizedJob]:
        self._need_queries()
        out: dict[str, NormalizedJob] = {}
        for page in range(1, 4):
            data = self._get_json("https://www.arbeitnow.com/api/job-board-api", params={"page": page}, max_attempts=2)
            items = (data or {}).get("data", [])
            for j in items:
                if title_matches(j.get("title", ""), self.queries):
                    n = self.normalize(j)
                    if n:
                        out[n.external_id] = n
            if not items or not (data or {}).get("links", {}).get("next"):
                break
        return list(out.values())

    @staticmethod
    def normalize(j: dict) -> Optional[NormalizedJob]:
        if not j.get("slug") or not j.get("title"):
            return None
        loc = j.get("location", "") or ""
        return NormalizedJob(
            external_id=str(j["slug"]), title=j["title"].strip(), company=j.get("company_name", "") or "Unknown",
            location=loc, remote_type="remote" if j.get("remote") else infer_remote_type(loc),
            employment_type=", ".join(j.get("job_types") or []), description_text=strip_html(j.get("description", "")),
            posted_at=_unix(j.get("created_at")), url=j.get("url", ""), apply_url=j.get("url", ""))


class HimalayasAdapter(KeywordAdapter):
    """Free remote jobs. Terms: link to Himalayas as the source, use their applicationLink unchanged."""

    kind = "himalayas"
    docs_url = "https://himalayas.app/api"
    label = "Himalayas (remote jobs)"

    def fetch(self) -> list[NormalizedJob]:
        self._need_queries()
        out: dict[str, NormalizedJob] = {}
        for q in self.queries[:3]:
            data = self._get_json("https://himalayas.app/jobs/api/search", params={"q": q, "sort": "recent"}, max_attempts=2)
            for j in (data or {}).get("jobs", []):
                if title_matches(j.get("title", ""), self.queries):
                    n = self.normalize(j)
                    if n:
                        out[n.external_id] = n
        return list(out.values())

    @staticmethod
    def normalize(j: dict) -> Optional[NormalizedJob]:
        gid = j.get("guid") or j.get("applicationLink")
        if not gid or not j.get("title"):
            return None
        locs = ", ".join(j.get("locationRestrictions") or []) or "Worldwide"
        period = (j.get("salaryPeriod") or "").lower()
        return NormalizedJob(
            external_id=str(gid), title=j["title"].strip(), company=j.get("companyName", "") or "Unknown",
            location="Remote — " + locs, remote_type="remote", employment_type=j.get("employmentType", "") or "",
            department=", ".join(j.get("categories") or [])[:200],
            description_text=strip_html(j.get("description", "") or j.get("excerpt", "")) + "\n\n(Listing via Himalayas)",
            salary_min=j.get("minSalary"), salary_max=j.get("maxSalary"), salary_currency=j.get("currency", "") or "",
            salary_interval="per-year-salary" if "year" in period or "annual" in period else period,
            posted_at=_unix(j.get("pubDate")), url=str(j.get("guid") or j.get("applicationLink")),
            apply_url=j.get("applicationLink", "") or str(gid))


class JobicyAdapter(KeywordAdapter):
    """Free remote jobs. Terms: credit Jobicy with a link; sync at most once per hour."""

    kind = "jobicy"
    docs_url = "https://jobicy.com/jobs-rss-feed"
    label = "Jobicy (remote jobs)"
    min_interval_hours = 1

    def fetch(self) -> list[NormalizedJob]:
        self._need_queries()
        out: dict[str, NormalizedJob] = {}
        for q in self.queries[:2]:
            tag = " ".join(core_words(q)) or q
            data = self._get_json("https://jobicy.com/api/jobs", params={"count": 100, "tag": tag}, max_attempts=2)
            for j in (data or {}).get("jobs", []):
                if title_matches(j.get("jobTitle", ""), self.queries):
                    n = self.normalize(j)
                    if n:
                        out[n.external_id] = n
        return list(out.values())

    @staticmethod
    def normalize(j: dict) -> Optional[NormalizedJob]:
        if not j.get("id") or not j.get("jobTitle"):
            return None
        jt = j.get("jobType")
        return NormalizedJob(
            external_id=str(j["id"]), title=strip_html(j["jobTitle"]), company=j.get("companyName", "") or "Unknown",
            location="Remote — " + (j.get("jobGeo") or "Anywhere"), remote_type="remote",
            employment_type=", ".join(jt) if isinstance(jt, list) else (jt or ""),
            department=", ".join(j["jobIndustry"]) if isinstance(j.get("jobIndustry"), list) else (j.get("jobIndustry") or ""),
            description_text=strip_html(j.get("jobDescription", "") or j.get("jobExcerpt", "")) + "\n\n(Listing via Jobicy)",
            salary_min=j.get("salaryMin"), salary_max=j.get("salaryMax"), salary_currency=j.get("salaryCurrency", "") or "",
            salary_interval="per-year-salary" if str(j.get("salaryPeriod", "")).lower().startswith("year") else str(j.get("salaryPeriod") or ""),
            posted_at=_dt(j.get("pubDate")), url=j.get("url", ""), apply_url=j.get("url", ""))


class JSearchAdapter(KeywordAdapter):
    """Google for Jobs results (LinkedIn, Indeed, Glassdoor, company sites…) via RapidAPI. Free plan: ~200 requests/month."""

    kind = "jsearch"
    requires_credentials = True
    docs_url = "https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch"
    label = "JSearch (LinkedIn, Indeed, Glassdoor via Google Jobs)"
    min_interval_hours = 12  # keep within the free monthly allowance

    def fetch(self) -> list[NormalizedJob]:
        self._need_queries()
        key = self.credentials.get("rapidapi_key")
        if not key:
            raise SourceError("jsearch: connect your free RapidAPI key in Settings → Connections.")
        out: dict[str, NormalizedJob] = {}
        loc = next((l for l in self.locations if l.lower() not in ("remote", "anywhere")), "")
        company = "" if self.identifier == "auto" else self.identifier
        if company:  # following one company through Google Jobs: one request per run
            q = self.queries[0]
            data = self._get_json_headers("https://jsearch.p.rapidapi.com/search",
                                          {"query": f"{q} at {company}", "page": 1, "num_pages": 1, "date_posted": "month", "country": "us"},
                                          {"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"})
            want = set(re.findall(r"[a-z0-9]+", company.lower()))
            for j in (data or {}).get("data", []) or []:
                emp = set(re.findall(r"[a-z0-9]+", (j.get("employer_name") or "").lower()))
                if want and want <= emp:
                    n = self.normalize(j)
                    if n:
                        out[n.external_id] = n
            return list(out.values())
        for q in self.queries[:2]:
            query = f"{q} in {loc}" if loc else f"{q} in USA"
            data = self._get_json_headers("https://jsearch.p.rapidapi.com/search",
                                          {"query": query, "page": 1, "num_pages": 1, "date_posted": "week", "country": "us"},
                                          {"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"})
            for j in (data or {}).get("data", []) or []:
                n = self.normalize(j)
                if n:
                    out[n.external_id] = n
        return list(out.values())

    @staticmethod
    def normalize(j: dict) -> Optional[NormalizedJob]:
        if not j.get("job_id") or not j.get("job_title"):
            return None
        loc = ", ".join(x for x in [j.get("job_city"), j.get("job_state"), j.get("job_country")] if x)
        period = (j.get("job_salary_period") or "").upper()
        return NormalizedJob(
            external_id=str(j["job_id"]), title=j["job_title"].strip(), company=j.get("employer_name", "") or "Unknown",
            location=loc or ("Remote" if j.get("job_is_remote") else ""),
            remote_type="remote" if j.get("job_is_remote") else infer_remote_type(loc),
            employment_type=(j.get("job_employment_type") or "").replace("FULLTIME", "Full-time"),
            description_text=strip_html(j.get("job_description", "")) + (f"\n\n(Found via {j['job_publisher']})" if j.get("job_publisher") else ""),
            salary_min=j.get("job_min_salary") if period == "YEAR" else None,
            salary_max=j.get("job_max_salary") if period == "YEAR" else None,
            salary_currency="USD" if period == "YEAR" and j.get("job_min_salary") else "",
            salary_interval="per-year-salary" if period == "YEAR" else "",
            posted_at=_dt(j.get("job_posted_at_datetime_utc")), url=j.get("job_apply_link", "") or "",
            apply_url=j.get("job_apply_link", "") or "")


class USAJobsAdapter(KeywordAdapter):
    """US federal government jobs (free key from developer.usajobs.gov). Most require US citizenship."""

    kind = "usajobs"
    requires_credentials = True
    docs_url = "https://developer.usajobs.gov/"
    label = "USAJOBS (US federal jobs)"

    def fetch(self) -> list[NormalizedJob]:
        self._need_queries()
        key, email = self.credentials.get("usajobs_key"), self.credentials.get("usajobs_email")
        if not key or not email:
            raise SourceError("usajobs: connect your free USAJOBS key and email in Settings → Connections.")
        out: dict[str, NormalizedJob] = {}
        for q in self.queries[:2]:
            params = {"Keyword": q, "ResultsPerPage": 50, "DatePosted": 14}
            loc = next((l for l in self.locations if l.lower() not in ("remote", "anywhere")), "")
            if loc:
                params["LocationName"] = loc
            data = self._get_json_headers("https://data.usajobs.gov/api/search", params,
                                          {"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": key})
            for item in ((data or {}).get("SearchResult") or {}).get("SearchResultItems", []):
                n = self.normalize(item.get("MatchedObjectDescriptor") or {})
                if n:
                    out[n.external_id] = n
        return list(out.values())

    @staticmethod
    def normalize(d: dict) -> Optional[NormalizedJob]:
        if not d.get("PositionID") or not d.get("PositionTitle"):
            return None
        pay = (d.get("PositionRemuneration") or [{}])[0]
        yearly = pay.get("RateIntervalCode") in ("PA", "Per Year")
        details = ((d.get("UserArea") or {}).get("Details") or {})
        duties = details.get("MajorDuties") or []
        desc = "\n\n".join(x for x in [details.get("JobSummary", ""), "\n".join(duties) if isinstance(duties, list) else str(duties),
                                       d.get("QualificationSummary", "")] if x)
        apply = (d.get("ApplyURI") or [d.get("PositionURI", "")])[0]
        return NormalizedJob(
            external_id=str(d["PositionID"]), title=d["PositionTitle"].strip(),
            company=d.get("OrganizationName") or d.get("DepartmentName") or "US Government",
            location=d.get("PositionLocationDisplay", "") or "", remote_type=infer_remote_type(d.get("PositionLocationDisplay", "")),
            department=d.get("DepartmentName", "") or "", description_text=strip_html(desc),
            salary_min=float(pay["MinimumRange"]) if yearly and pay.get("MinimumRange") else None,
            salary_max=float(pay["MaximumRange"]) if yearly and pay.get("MaximumRange") else None,
            salary_currency="USD" if yearly else "", salary_interval="per-year-salary" if yearly else "",
            posted_at=_dt(d.get("PublicationStartDate")), url=d.get("PositionURI", "") or apply, apply_url=apply)
