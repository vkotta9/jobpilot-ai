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
    detail_limit = 60

    def __init__(self, identifier: str, **kw):
        super().__init__(identifier, **kw)
        self.queries: list[str] = []
        self.title_filter = None
        self.display = ""
        self.known_described = frozenset()

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

    def _want_detail(self, title: str, done: int, ext_id=None) -> bool:
        if ext_id is not None and str(ext_id) in self.known_described:
            return False
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
        try:
            return self._fetch_v2(base)
        except SourceError as e:
            if e.status not in (401, 403):
                raise
        return self._fetch_pcsx()

    def _fetch_pcsx(self) -> list[NormalizedJob]:
        base = f"https://{self.host}/api/pcsx"
        self._allowed(base + "/search")
        positions: dict[str, dict] = {}
        for q in self._searches():
            for start in (0, 10, 20):
                data = self._get_json(base + "/search", params={"domain": self.domain, "query": q, "location": "United States",
                                                                "start": start, "sort_by": "timestamp"})
                items = ((data or {}).get("data") or {}).get("positions") or []
                for p in items:
                    if p.get("id"):
                        positions[str(p["id"])] = p
                if len(items) < 10:
                    break
        out, done = [], 0
        for pid, p in positions.items():
            desc, url = "", ""
            if self._want_detail(p.get("name", ""), done, pid):
                if done:
                    self._sleep(1.5)  # the site rate-limits bursts of detail requests
                try:
                    d = self._pcsx_detail(pid)
                    desc, url = strip_html(d.get("jobDescription", "") or ""), d.get("publicUrl") or ""
                    done += 1
                except SourceError:
                    pass
            if not p.get("name"):
                continue
            loc = "; ".join(p.get("standardizedLocations") or p.get("locations") or [])
            url = url or (f"https://{self.host}{p['positionUrl']}" if str(p.get("positionUrl", "")).startswith("/") else p.get("positionUrl") or
                          f"https://{self.host}/careers?pid={pid}&domain={self.domain}")
            out.append(NormalizedJob(
                external_id=str(pid), title=p["name"].strip(), company=self.company_name(), location=loc,
                remote_type={"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}.get(str(p.get("workLocationOption", "")).lower(), infer_remote_type(loc)),
                department=p.get("department", "") or "", description_text=desc, posted_at=_dt(p.get("postedTs") or p.get("creationTs")),
                url=url, apply_url=url))
        return out

    def _pcsx_detail(self, pid: str) -> dict:
        return (self._get_json(f"https://{self.host}/api/pcsx/position_details",
                               params={"position_id": pid, "domain": self.domain, "hl": "en"}, max_attempts=2) or {}).get("data") or {}

    def describe(self, external_id: str, url: str) -> Optional[str]:
        try:
            return strip_html(self._pcsx_detail(external_id).get("jobDescription", "") or "") or None
        except SourceError:
            d = self._get_json(f"https://{self.host}/api/apply/v2/jobs/{external_id}", params={"domain": self.domain}, max_attempts=1)
            return strip_html((d or {}).get("job_description", "") or "") or None

    def _fetch_v2(self, base: str) -> list[NormalizedJob]:
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
            if not desc and self._want_detail(p.get("name", ""), done, pid):
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
            if self._want_detail(r.get("Title", ""), done, rid):
                try:
                    desc = self.describe(rid, "") or desc
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

    def describe(self, external_id: str, url: str) -> Optional[str]:
        det_api = f"https://{self.host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
        finder = f'ById;Id="{external_id}",siteNumber={self.site}'
        d = self._get_json(det_api + "?expand=all&onlyData=true&finder=" + quote(finder, safe="=;,"), max_attempts=2)
        it = ((d or {}).get("items") or [{}])[0]
        return "\n\n".join(strip_html(it.get(k, "") or "") for k in
                           ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr") if it.get(k)) or None


class MicrosoftAdapter(_CareersSiteAdapter):
    """Microsoft careers (apply.careers.microsoft.com, Eightfold)."""

    kind = "microsoft"
    docs_url = "https://careers.microsoft.com/"

    def company_name(self) -> str:
        return "Microsoft"

    def fetch(self) -> list[NormalizedJob]:
        ef = EightfoldAdapter("apply.careers.microsoft.com|microsoft.com", transport=self._transport, sleep=self._sleep)
        ef.queries, ef.title_filter, ef.detail_limit, ef.display, ef.timeout_s = self.queries, self.title_filter, self.detail_limit, "Microsoft", self.timeout_s
        ef.detail_limit, ef.known_described = min(self.detail_limit, 25), self.known_described
        return ef._fetch_pcsx()

    def describe(self, external_id: str, url: str) -> Optional[str]:
        return EightfoldAdapter("apply.careers.microsoft.com|microsoft.com", transport=self._transport).describe(external_id, url)


class GoogleAdapter(_CareersSiteAdapter):
    """Google Careers: the results page lists job links; each job page has the full description."""

    kind = "google"
    docs_url = "https://www.google.com/about/careers/applications/jobs/results"
    BASE = "https://www.google.com/about/careers/applications/jobs/results"

    def company_name(self) -> str:
        return "Google"

    def _html(self, url: str, params: Optional[dict] = None) -> str:
        with httpx.Client(timeout=self.timeout_s or 20, transport=self._transport, follow_redirects=True,
                          headers={"User-Agent": settings.user_agent, "Accept": "text/html"}) as c:
            r = c.get(url, params=params)
        if r.status_code >= 400:
            raise SourceError(f"google: careers page returned HTTP {r.status_code}", status=r.status_code)
        return r.text

    def fetch(self) -> list[NormalizedJob]:
        self._allowed(self.BASE)
        found: dict[str, str] = {}
        for q in self._searches():
            html = self._html(self.BASE, {"q": q, "location": "United States", "sort_by": "date"})
            for jid, slug in re.findall(r"jobs/results/(\d{6,})-([a-z0-9-]+)", html):
                found.setdefault(jid, slug)
        out, done = [], 0
        for jid, slug in list(found.items())[:60]:
            title = slug.replace("-", " ").title()
            desc, loc = "", ""
            if self._want_detail(title, done, jid):
                try:
                    title2, desc, loc = self._parse_job(self._html(f"{self.BASE}/{jid}-{slug}"))
                    title = title2 or title
                    done += 1
                except SourceError:
                    pass
            url = f"{self.BASE}/{jid}-{slug}"
            out.append(NormalizedJob(external_id=jid, title=title, company="Google", location=loc, remote_type=infer_remote_type(loc),
                                     description_text=desc, url=url, apply_url=url))
        return out


def _google_parse(page: str) -> tuple[str, str, str]:
    title = ""
    m = re.search(r"<title>([^<|–—]+)", page)
    if m and "google" not in m.group(1).lower()[:8]:
        title = re.sub(r"\s*[—–-]\s*Google Careers.*$", "", m.group(1)).strip()
    text = strip_html(page)
    desc = ""
    i = text.find("Minimum qualifications")
    if i >= 0:
        end = min([k for k in (text.find("Google is proud to be", i), text.find("Information collected and processed", i)) if k > 0] or [i + 8000])
        desc = text[i:end].strip()
    lm = re.search(r"place\s*([^\n]{3,160})", text)
    return title, desc, (lm.group(1).strip() if lm else "")


GoogleAdapter._parse_job = staticmethod(_google_parse)
GoogleAdapter.describe = lambda self, external_id, url: _google_parse(self._html(url))[1] or None


class AppleAdapter(_CareersSiteAdapter):
    """Apple Jobs: search results and job details are embedded as data in the pages."""

    kind = "apple"
    docs_url = "https://jobs.apple.com/"
    BASE = "https://jobs.apple.com/en-us"

    def company_name(self) -> str:
        return "Apple"

    def _page_data(self, url: str, params: Optional[dict] = None) -> dict:
        with httpx.Client(timeout=self.timeout_s or 20, transport=self._transport, follow_redirects=True,
                          headers={"User-Agent": settings.user_agent, "Accept": "text/html"}) as c:
            r = c.get(url, params=params)
        if r.status_code >= 400:
            raise SourceError(f"apple: page returned HTTP {r.status_code}", status=r.status_code)
        m = re.search(r'__staticRouterHydrationData\s*=\s*JSON\.parse\((".*?")\);', r.text, re.S)
        if not m:
            raise SourceError("apple: page data not found")
        import json as _json

        return _json.loads(_json.loads(m.group(1)))

    @staticmethod
    def _find(obj, key: str):
        """Depth-first search for the first list of dicts containing `key` (or a dict with `key`)."""
        stack = [obj]
        while stack:
            o = stack.pop()
            if isinstance(o, list):
                if o and all(isinstance(x, dict) for x in o) and key in o[0]:
                    return o
                stack.extend(o)
            elif isinstance(o, dict):
                if key in o and not isinstance(o[key], (dict, list)):
                    return o
                stack.extend(o.values())
        return None

    def fetch(self) -> list[NormalizedJob]:
        self._allowed(f"{self.BASE}/search")
        rows: dict[str, dict] = {}
        for q in self._searches():
            data = self._page_data(f"{self.BASE}/search", {"search": q, "sort": "newest", "location": "united-states-USA"})
            for r in self._find(data, "postingTitle") or []:
                pid = str(r.get("positionId") or r.get("id") or "")
                if pid:
                    rows[pid] = r
        out, done = [], 0
        for pid, r in rows.items():
            title = (r.get("postingTitle") or "").strip()
            slug = r.get("transformedPostingTitle") or re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            url = f"{self.BASE}/details/{pid}/{slug}"
            desc = r.get("jobSummary", "") or ""
            if self._want_detail(title, done, pid):
                try:
                    desc = self.describe(pid, url) or desc
                    done += 1
                except SourceError:
                    pass
            locs = r.get("locations") or []
            loc = "; ".join(", ".join(x for x in [l.get("name"), l.get("countryName")] if x) for l in locs if isinstance(l, dict))
            out.append(NormalizedJob(external_id=pid, title=title, company="Apple", location=loc, remote_type=infer_remote_type(loc),
                                     department=((r.get("team") or {}).get("teamName") if isinstance(r.get("team"), dict) else "") or "",
                                     description_text=strip_html(desc), posted_at=_dt(r.get("postDateInGMT") or r.get("postingDate")),
                                     url=url, apply_url=url))
        return [n for n in out if n.title]

    def describe(self, external_id: str, url: str) -> Optional[str]:
        data = self._page_data(url)
        d = self._find(data, "description") or self._find(data, "jobSummary") or {}
        if not isinstance(d, dict):
            return None
        parts = [d.get(k) for k in ("jobSummary", "description", "responsibilities", "minimumQualifications",
                                     "preferredQualifications") if isinstance(d.get(k), str)]
        return "\n\n".join(strip_html(x) for x in parts if x) or None


# link patterns for detection
EIGHTFOLD_RE = re.compile(r"https?://([A-Za-z0-9.-]+)/(?:careers|api/apply/v2)[^\s\"'<>]*?domain=([A-Za-z0-9.-]+)", re.I)
ORACLE_RE = re.compile(r"https?://([A-Za-z0-9.-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z-]+/sites/(CX_?\w+)", re.I)


def parse_link(text: str) -> Optional[tuple[str, str]]:
    t = text or ""
    if re.search(r"amazon\.jobs", t, re.I):
        return ("amazon", "amazon")
    if re.search(r"careers\.google\.com|google\.com/about/careers", t, re.I):
        return ("google", "google")
    if re.search(r"jobs\.apple\.com", t, re.I):
        return ("apple", "apple")
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
