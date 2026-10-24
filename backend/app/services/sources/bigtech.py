"""Connectors for careers sites that aren't on a shared job board.

Each reads the same public listing data the careers site loads in your browser,
only after checking that the site's robots.txt allows it, searching for your
target titles, at most once a day, with a small cap on detail requests.

  amazon     amazon.jobs                      identifier: "amazon"
  google     Google Careers                   identifier: "google"
  eightfold  Eightfold-powered careers sites  identifier: "<host>|<domain>"  e.g. "apply.careers.microsoft.com|microsoft.com"
  oraclehcm  Oracle Recruiting Cloud sites    identifier: "<host>|<siteNumber>" e.g. "eeho.fa.us2.oraclecloud.com|CX_45001"
"""
from __future__ import annotations

import re
import urllib.robotparser
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote, urlparse

import httpx

from ...config import settings
from ..textutil import strip_html
from .base import JobSourceAdapter, NormalizedJob, SourceError, infer_remote_type


def _dt(s) -> Optional[datetime]:
    if s in (None, ""):
        return None
    if isinstance(s, (int, float)):
        v = s / 1000 if s > 1e12 else s
        return datetime.fromtimestamp(v, tz=timezone.utc).replace(tzinfo=None)
    s = str(s).strip()
    try:
        return datetime.strptime(s, "%B %d, %Y")
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return None


class _CareersSiteAdapter(JobSourceAdapter):
    partial = True          # we search the site, so a missing job isn't necessarily closed
    min_interval_hours = 20
    detail_limit = 25

    def __init__(self, identifier: str, **kw):
        super().__init__(identifier, **kw)
        self.queries: list[str] = []
        self.title_filter = None
        self.display = ""

    def _allowed(self, url: str) -> None:
        parts = urlparse(url)
        rp = urllib.robotparser.RobotFileParser()
        try:
            with httpx.Client(timeout=10, transport=self._transport, follow_redirects=True,
                              headers={"User-Agent": settings.user_agent}) as c:
                r = c.get(f"{parts.scheme}://{parts.netloc}/robots.txt")
            if r.status_code >= 400:
                return
            rp.parse(r.text.splitlines())
        except httpx.HTTPError:
            return
        if not rp.can_fetch(settings.user_agent, url):
            raise SourceError(f"{self.kind}: {parts.netloc}'s robots.txt doesn't allow automated access to its job search.")

    def _searches(self) -> list[str]:
        return self.queries[:3] or ["software engineer"]

    def _want_detail(self, title: str, done: int) -> bool:
        return done < self.detail_limit and (self.title_filter is None or self.title_filter(title))


class AmazonAdapter(_CareersSiteAdapter):
    kind = "amazon"
    docs_url = "https://www.amazon.jobs/"

    def company_name(self) -> str:
        return "Amazon"

    def fetch(self) -> list[NormalizedJob]:
        base = "https://www.amazon.jobs/en/search.json"
        self._allowed(base)
        out: dict[str, NormalizedJob] = {}
        for q in self._searches():
            data = self._get_json(base, params={"base_query": q, "result_limit": 100, "sort": "recent",
                                                "normalized_country_code[]": "USA"})
            for j in (data or {}).get("jobs") or []:
                n = self.normalize(j)
                if n:
                    out[n.external_id] = n
        return list(out.values())

    @staticmethod
    def normalize(j: dict) -> Optional[NormalizedJob]:
        jid = j.get("id_icims") or j.get("id")
        if not jid or not j.get("title"):
            return None
        desc = "\n\n".join(x for x in [strip_html(j.get("description", "")),
                                       "Basic qualifications:\n" + strip_html(j.get("basic_qualifications", "")) if j.get("basic_qualifications") else "",
                                       "Preferred qualifications:\n" + strip_html(j.get("preferred_qualifications", "")) if j.get("preferred_qualifications") else ""] if x)
        url = "https://www.amazon.jobs" + j["job_path"] if j.get("job_path") else ""
        loc = j.get("normalized_location") or j.get("location", "")
        return NormalizedJob(
            external_id=str(jid), title=j["title"].strip(), company=j.get("company_name") or "Amazon", location=loc,
            remote_type=infer_remote_type(loc), department=j.get("job_category", "") or "", description_text=desc,
            posted_at=_dt(j.get("posted_date")), url=url, apply_url=url)


class GoogleAdapter(_CareersSiteAdapter):
    kind = "google"
    docs_url = "https://careers.google.com/"

    def company_name(self) -> str:
        return "Google"

    def fetch(self) -> list[NormalizedJob]:
        base = "https://careers.google.com/api/v3/search/"
        self._allowed(base)
        out: dict[str, NormalizedJob] = {}
        for q in self._searches():
            for page in (1, 2):
                data = self._get_json(base, params={"q": q, "page": page, "distance": 50, "location": "United States"})
                items = (data or {}).get("jobs") or []
                for j in items:
                    n = self.normalize(j)
                    if n:
                        out[n.external_id] = n
                if not (data or {}).get("next_page"):
                    break
        return list(out.values())

    @staticmethod
    def normalize(j: dict) -> Optional[NormalizedJob]:
        if not j.get("id") or not j.get("title"):
            return None
        jid = str(j["id"]).split("/")[-1]
        locs = "; ".join(l.get("display", "") for l in j.get("locations") or [] if l.get("display"))
        desc = "\n\n".join(strip_html(j.get(k, "")) for k in ("description", "responsibilities", "qualifications") if j.get(k))
        url = j.get("apply_url") or f"https://www.google.com/about/careers/applications/jobs/results/{jid}"
        return NormalizedJob(
            external_id=jid, title=j["title"].strip(), company=j.get("company_name") or "Google", location=locs,
            remote_type=infer_remote_type(locs), description_text=desc, posted_at=_dt(j.get("publish_date") or j.get("created")),
            url=url, apply_url=url)


class EightfoldAdapter(_CareersSiteAdapter):
    """Eightfold AI careers sites (Microsoft, Netflix, Qualcomm, …)."""

    kind = "eightfold"
    docs_url = "https://eightfold.ai/"

    def __init__(self, identifier: str, **kw):
        super().__init__(identifier, **kw)
        try:
            self.host, self.domain = identifier.split("|")
        except ValueError:
            raise SourceError("eightfold: identifier must look like host|domain")

    def company_name(self) -> str:
        return self.display or self.domain.split(".")[0].title()

    def fetch(self) -> list[NormalizedJob]:
        base = f"https://{self.host}/api/apply/v2/jobs"
        self._allowed(base)
        positions: dict[str, dict] = {}
        for q in self._searches():
            for start in (0, 10, 20):
                data = self._get_json(base, params={"domain": self.domain, "query": q, "location": "United States",
                                                    "start": start, "num": 10, "sort_by": "timestamp"})
                items = (data or {}).get("positions") or []
                for p in items:
                    if p.get("id"):
                        positions[str(p["id"])] = p
                if len(items) < 10:
                    break
        out, done = [], 0
        for pid, p in positions.items():
            desc = strip_html(p.get("job_description", "") or "")
            if not desc and self._want_detail(p.get("name", ""), done):
                try:
                    d = self._get_json(f"{base}/{pid}", params={"domain": self.domain}, max_attempts=1)
                    desc = strip_html((d or {}).get("job_description", "") or "")
                    done += 1
                except SourceError:
                    pass
            n = self.normalize(p, desc)
            if n:
                out.append(n)
        return out

    def normalize(self, p: dict, desc: str) -> Optional[NormalizedJob]:
        if not p.get("name"):
            return None
        loc = p.get("location") or "; ".join(p.get("locations") or [])
        url = p.get("canonicalPositionUrl") or f"https://{self.host}/careers?pid={p['id']}&domain={self.domain}"
        return NormalizedJob(
            external_id=str(p["id"]), title=p["name"].strip(), company=self.company_name(), location=loc,
            remote_type="remote" if str(p.get("work_location_option", "")).lower() == "remote" else infer_remote_type(loc),
            department=p.get("department", "") or "", description_text=desc, posted_at=_dt(p.get("t_create")),
            url=url, apply_url=url)


class OracleHCMAdapter(_CareersSiteAdapter):
    """Oracle Recruiting Cloud candidate sites (Oracle, JPMorgan Chase, …)."""

    kind = "oraclehcm"
    docs_url = "https://docs.oracle.com/en/cloud/saas/human-resources/"

    def __init__(self, identifier: str, **kw):
        super().__init__(identifier, **kw)
        try:
            self.host, self.site = identifier.split("|")
        except ValueError:
            raise SourceError("oraclehcm: identifier must look like host|siteNumber")

    def company_name(self) -> str:
        return self.display or self.host.split(".")[0].upper()

    def fetch(self) -> list[NormalizedJob]:
        api = f"https://{self.host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
        self._allowed(api)
        reqs: dict[str, dict] = {}
        for q in self._searches():
            finder = f'findReqs;siteNumber={self.site},limit=25,keyword="{q}",sortBy=POSTING_DATES_DESC'
            data = self._get_json(api + "?onlyData=true&expand=requisitionList.secondaryLocations&finder=" + quote(finder, safe="=;,"))
            for item in (data or {}).get("items") or []:
                for r in item.get("requisitionList") or []:
                    if r.get("Id"):
                        reqs[str(r["Id"])] = r
        out, done = [], 0
        det_api = f"https://{self.host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
        for rid, r in reqs.items():
            desc = strip_html(r.get("ShortDescriptionStr", "") or "")
            if self._want_detail(r.get("Title", ""), done):
                try:
                    finder = f'ById;Id="{rid}",siteNumber={self.site}'
                    d = self._get_json(det_api + "?expand=all&onlyData=true&finder=" + quote(finder, safe="=;,"), max_attempts=1)
                    it = ((d or {}).get("items") or [{}])[0]
                    full = "\n\n".join(strip_html(it.get(k, "") or "") for k in
                                       ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr") if it.get(k))
                    desc = full or desc
                    done += 1
                except SourceError:
                    pass
            url = f"https://{self.host}/hcmUI/CandidateExperience/en/sites/{self.site}/job/{rid}"
            loc = r.get("PrimaryLocation", "") or ""
            out.append(NormalizedJob(
                external_id=rid, title=(r.get("Title") or "").strip(), company=self.company_name(), location=loc,
                remote_type="remote" if "remote" in str(r.get("WorkplaceType", "")).lower() else infer_remote_type(loc),
                description_text=desc, posted_at=_dt(r.get("PostedDate")), url=url, apply_url=url))
        return [n for n in out if n.title]


class MicrosoftAdapter(_CareersSiteAdapter):
    """Microsoft careers: Eightfold-powered site, with the older careers search API as a fallback."""

    kind = "microsoft"
    docs_url = "https://careers.microsoft.com/"

    def company_name(self) -> str:
        return "Microsoft"

    def fetch(self) -> list[NormalizedJob]:
        try:
            ef = EightfoldAdapter("apply.careers.microsoft.com|microsoft.com", transport=self._transport, sleep=self._sleep)
            ef.queries, ef.title_filter, ef.detail_limit, ef.display, ef.timeout_s = self.queries, self.title_filter, self.detail_limit, "Microsoft", self.timeout_s
            jobs = ef.fetch()
            if jobs:
                return jobs
        except SourceError:
            pass
        base = "https://gcsservices.careers.microsoft.com/search/api/v1/search"
        self._allowed(base)
        out: dict[str, NormalizedJob] = {}
        for q in self._searches():
            data = self._get_json(base, params={"q": q, "lc": "United States", "l": "en_us", "pg": 1, "pgSz": 20, "o": "Recent", "flt": "true"})
            for j in (((data or {}).get("operationResult") or {}).get("result") or {}).get("jobs") or []:
                props = j.get("properties") or {}
                loc = props.get("primaryLocation") or "; ".join(props.get("locations") or [])
                url = f"https://jobs.careers.microsoft.com/global/en/job/{j.get('jobId')}"
                if j.get("jobId") and j.get("title"):
                    out[str(j["jobId"])] = NormalizedJob(
                        external_id=str(j["jobId"]), title=j["title"].strip(), company="Microsoft", location=loc,
                        remote_type=infer_remote_type(loc, props.get("workSiteFlexibility", "") or ""),
                        description_text=strip_html(props.get("description", "") or ""), posted_at=_dt(j.get("postingDate")),
                        url=url, apply_url=url)
        if not out:
            raise SourceError("microsoft: careers search returned no jobs")
        return list(out.values())


# link patterns for detection
EIGHTFOLD_RE = re.compile(r"https?://([A-Za-z0-9.-]+)/(?:careers|api/apply/v2)[^\s\"'<>]*?domain=([A-Za-z0-9.-]+)", re.I)
ORACLE_RE = re.compile(r"https?://([A-Za-z0-9.-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z-]+/sites/(CX_?\w+)", re.I)


def parse_link(text: str) -> Optional[tuple[str, str]]:
    t = text or ""
    if re.search(r"amazon\.jobs", t, re.I):
        return ("amazon", "amazon")
    if re.search(r"careers\.google\.com|google\.com/about/careers", t, re.I):
        return ("google", "google")
    if re.search(r"careers\.microsoft\.com", t, re.I):
        return ("microsoft", "microsoft")
    if re.search(r"jobs\.netflix\.(com|net)|explore\.jobs\.netflix\.net", t, re.I):
        return ("eightfold", "explore.jobs.netflix.net|netflix.com")
    m = ORACLE_RE.search(t)
    if m:
        return ("oraclehcm", f"{m.group(1).lower()}|{m.group(2)}")
    m = EIGHTFOLD_RE.search(t)
    if m:
        return ("eightfold", f"{m.group(1).lower()}|{m.group(2).lower()}")
    return None
