"""Workday career sites (e.g. https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite).

Workday has no official public jobs API, but every Workday careers site loads
its listings from a JSON endpoint on the same host, and the sites' robots.txt
allow crawling the careers pages. JobPilot reads that same public data, gently:
robots.txt is checked first, only searches for your target titles, at most once
a day, with a small cap on job-detail requests.

Identifier format: "<tenant>|<wdN>|<site>"  e.g. "nvidia|wd5|NVIDIAExternalCareerSite"
"""
from __future__ import annotations

import re
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from ...config import settings
from ..textutil import strip_html
from .base import JobSourceAdapter, NormalizedJob, SourceError, infer_remote_type

URL_RE = re.compile(r"https?://([A-Za-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)", re.I)
POSTED_RE = re.compile(r"(\d+)\+?\s+days?\s+ago", re.I)


def parse_url(text: str) -> Optional[str]:
    m = URL_RE.search(text or "")
    if not m:
        return None
    tenant, wd, site = m.group(1).lower(), m.group(2).lower(), m.group(3)
    if site.lower() in ("wday", "en-us", "job", "details"):
        return None
    return f"{tenant}|{wd}|{site}"


def _posted(text: str) -> Optional[datetime]:
    t = (text or "").lower()
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    if "today" in t:
        return now
    if "yesterday" in t:
        return now - timedelta(days=1)
    m = POSTED_RE.search(t)
    return now - timedelta(days=int(m.group(1))) if m else None


class WorkdayAdapter(JobSourceAdapter):
    kind = "workday"
    partial = True  # we search, so missing jobs aren't necessarily closed
    min_interval_hours = 20
    detail_limit = 30
    docs_url = "https://www.workday.com/"

    def __init__(self, identifier: str, **kw):
        super().__init__(identifier, **kw)
        try:
            self.tenant, self.wd, self.site = identifier.split("|")
        except ValueError:
            raise SourceError("workday: identifier must look like tenant|wd5|SiteName")
        self.host = f"https://{self.tenant}.{self.wd}.myworkdayjobs.com"
        self.queries: list[str] = []
        self.title_filter = None

    def company_name(self) -> str:
        return self.tenant.replace("-", " ").title()

    def _robots_ok(self) -> bool:
        rp = urllib.robotparser.RobotFileParser()
        try:
            with httpx.Client(timeout=10, transport=self._transport, headers={"User-Agent": settings.user_agent}) as c:
                r = c.get(f"{self.host}/robots.txt")
            if r.status_code >= 400:
                return True
            rp.parse(r.text.splitlines())
            return rp.can_fetch(settings.user_agent, f"{self.host}/{self.site}")
        except httpx.HTTPError:
            return True

    def fetch(self) -> list[NormalizedJob]:
        if not self._robots_ok():
            raise SourceError(f"workday: {self.tenant}'s robots.txt doesn't allow automated access to this careers site.")
        api = f"{self.host}/wday/cxs/{self.tenant}/{self.site}"
        searches = self.queries[:3] or [""]
        postings: dict[str, dict] = {}
        for q in searches:
            for offset in (0, 20):
                data = self._post_json(f"{api}/jobs", {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": q})
                items = (data or {}).get("jobPostings") or []
                for it in items:
                    if it.get("externalPath"):
                        postings[it["externalPath"]] = it
                if len(items) < 20:
                    break
        out = []
        details = 0
        for path, it in postings.items():
            title = it.get("title", "")
            desc, extra = "", {}
            if (self.title_filter is None or self.title_filter(title)) and details < self.detail_limit:
                try:
                    d = self._get_json(f"{api}{path}", max_attempts=1)
                    extra = (d or {}).get("jobPostingInfo") or {}
                    desc = strip_html(extra.get("jobDescription", ""))
                    details += 1
                except SourceError:
                    pass
            loc = extra.get("location") or it.get("locationsText", "")
            url = extra.get("externalUrl") or f"{self.host}/{self.site}{path}"
            posted = None
            if extra.get("startDate"):
                try:
                    posted = datetime.fromisoformat(extra["startDate"][:10])
                except ValueError:
                    posted = None
            out.append(NormalizedJob(
                external_id=extra.get("jobReqId") or path, title=title.strip(), company=self.company_name(),
                location=loc, remote_type=infer_remote_type(loc, extra.get("remoteType", "") or ""),
                employment_type=extra.get("timeType", "") or "", description_text=desc,
                posted_at=posted or _posted(it.get("postedOn", "")), url=url, apply_url=url))
        return out


WD_INSTANCES = ("wd1", "wd5", "wd3", "wd12", "wd10", "wd2", "wd103", "wd501")
SITEMAP_RE = re.compile(r"Sitemap:\s*https?://([A-Za-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)/siteMap\.xml", re.I)


def discover(name: str, transport=None) -> list[str]:
    """Find a company's Workday career site(s) by name. Each Workday tenant's robots.txt lists its
    public career sites as sitemaps, so this needs only a few small GETs."""
    words = re.findall(r"[a-z0-9]+", name.lower())
    tenants = list(dict.fromkeys(["".join(words), "-".join(words)] + ([words[0]] if words else [])))
    found: list[str] = []
    with httpx.Client(timeout=6, transport=transport, follow_redirects=False,
                      headers={"User-Agent": settings.user_agent}) as c:
        for tenant in tenants[:3]:
            for wd in WD_INSTANCES:
                try:
                    r = c.get(f"https://{tenant}.{wd}.myworkdayjobs.com/robots.txt")
                except httpx.HTTPError:
                    continue
                if r.status_code != 200:
                    continue
                for m in SITEMAP_RE.finditer(r.text):
                    if m.group(1).lower() == tenant:
                        ident = f"{tenant}|{m.group(2).lower()}|{m.group(3)}"
                        if ident not in found:
                            found.append(ident)
                if found:
                    return found
    return found
