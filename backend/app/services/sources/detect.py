"""Turn a careers-page link or a company name into a followable job board.

* Links on a known job-board host (greenhouse.io, lever.co, ashbyhq.com,
  smartrecruiters.com, workable.com, recruitee.com) are parsed directly.
* Any other link (e.g. https://stripe.com/jobs) is fetched once — only if the
  site's robots.txt allows it — and scanned for an embedded job-board link.
* A plain company name is tried as a board slug on each platform's public API.

Workday, iCIMS, Taleo, SuccessFactors, Oracle and in-house career sites
(Google, Amazon, Microsoft, Apple…) have no public job feed, so they are
reported as unsupported instead of being scraped.
"""
from __future__ import annotations

import re
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

from ...config import settings
from .base import SourceError
from .workday import parse_url as workday_parse
from .workday import discover as workday_discover
from .bigtech import parse_link as careers_link

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?([A-Za-z0-9_-]+)", re.I)),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_.-]+)", re.I)),
    ("lever", re.compile(r"api\.(?:eu\.)?lever\.co/v0/postings/([A-Za-z0-9_.-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)", re.I)),
    ("ashby", re.compile(r"api\.ashbyhq\.com/posting-api/job-board/([A-Za-z0-9_.%-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/(?:api/v\d/widget/accounts/)?([A-Za-z0-9_-]+)", re.I)),
    ("workable", re.compile(r"(?<![\w.-])([A-Za-z0-9-]+)\.workable\.com", re.I)),
    ("recruitee", re.compile(r"(?<![\w.-])([A-Za-z0-9-]+)\.recruitee\.com", re.I)),
]
UNSUPPORTED = [
    ("iCIMS", re.compile(r"icims\.com", re.I)),
    ("Taleo", re.compile(r"taleo\.net", re.I)),
    ("SuccessFactors", re.compile(r"successfactors|sapsf\.", re.I)),
    ("Oracle Cloud", re.compile(r"oraclecloud\.com/hcmUI|fa\.\w+\.oraclecloud", re.I)),
    ("Jobvite", re.compile(r"jobvite\.com", re.I)),
    ("BambooHR", re.compile(r"bamboohr\.com/careers", re.I)),
]
# Companies with their own careers sites (no public feed): followed through Google Jobs (JSearch) instead
IN_HOUSE = {"google": "Google", "alphabet": "Google", "amazon": "Amazon", "aws": "Amazon", "microsoft": "Microsoft",
            "apple": "Apple", "meta": "Meta", "facebook": "Meta", "netflix": "Netflix", "ibm": "IBM", "oracle": "Oracle",
            "tesla": "Tesla", "uber": "Uber", "linkedin": "LinkedIn", "bytedance": "ByteDance", "tiktok": "TikTok",
            "jpmorgan": "JPMorgan Chase", "jpmorganchase": "JPMorgan Chase", "goldmansachs": "Goldman Sachs",
            "bloomberg": "Bloomberg", "qualcomm": "Qualcomm", "cisco": "Cisco", "x": "X", "twitter": "X"}
# Companies with their own careers sites that JobPilot has a direct connector for
CUSTOM_BY_NAME = {
    "amazon": ("amazon", "amazon", "Amazon"), "aws": ("amazon", "amazon", "Amazon"), "amazonwebservices": ("amazon", "amazon", "Amazon"),
    "google": ("google", "google", "Google"), "alphabet": ("google", "google", "Google"),
    "microsoft": ("microsoft", "microsoft", "Microsoft"),
    "netflix": ("eightfold", "explore.jobs.netflix.net|netflix.com", "Netflix"),
    "oracle": ("oraclehcm", "eeho.fa.us2.oraclecloud.com|CX_45001", "Oracle"),
    "jpmorgan": ("oraclehcm", "jpmc.fa.oraclecloud.com|CX_1001", "JPMorgan Chase"),
    "jpmorganchase": ("oraclehcm", "jpmc.fa.oraclecloud.com|CX_1001", "JPMorgan Chase"),
}
# Well-known companies on Workday (verified live — see scripts/validate_companies.py)
KNOWN_WORKDAY = {"nvidia": "nvidia|wd5|NVIDIAExternalCareerSite", "salesforce": "salesforce|wd12|External_Career_Site", "intel": "intel|wd1|External", "adobe": "adobe|wd5|external_experienced", "hp": "hp|wd5|ExternalCareerSite", "hpinc": "hp|wd5|ExternalCareerSite", "paypal": "paypal|wd1|jobs", "capitalone": "capitalone|wd12|Capital_One", "mastercard": "mastercard|wd1|CorporateCareers", "boeing": "boeing|wd1|EXTERNAL_CAREERS", "target": "target|wd5|targetcareers", "disney": "disney|wd5|disneycareer", "waltdisney": "disney|wd5|disneycareer", "thewaltdisneycompany": "disney|wd5|disneycareer", "workday": "workday|wd5|Workday", "snap": "snapchat|wd1|snap", "snapchat": "snapchat|wd1|snap", "snapinc": "snapchat|wd1|snap", "autodesk": "autodesk|wd1|Ext"}
IGNORE_SLUGS = {"embed", "api", "jobs", "careers", "www", "apply", "job_board", "v1", "boards", "js"}
PROBE_ORDER = ("greenhouse", "lever", "ashby", "workable", "recruitee", "smartrecruiters")


@dataclass
class Detection:
    input: str
    status: str  # found | unsupported | not_found | error
    kind: str = ""
    identifier: str = ""
    company: str = ""
    jobs: int = 0
    message: str = ""

    def dict(self) -> dict:
        return asdict(self)


def _adapter(kind: str, ident: str, transport=None):
    from . import ADAPTERS

    a = ADAPTERS[kind](ident, transport=transport, sleep=lambda s: None)
    a.timeout_s = 10
    if kind == "smartrecruiters":
        a.detail_limit = 0
    return a


def probe(kind: str, ident: str, transport=None) -> Optional[Detection]:
    """Ask the platform's public API whether this board exists. Returns None if not."""
    try:
        a = _adapter(kind, ident, transport)
        original_get = a._get_json
        a._get_json = lambda url, params=None, max_attempts=1: original_get(url, params=params, max_attempts=1)
        jobs = a.fetch()
    except SourceError:
        return None
    except Exception:
        return None
    if kind == "smartrecruiters" and not jobs:
        return None  # unknown SmartRecruiters ids return an empty list instead of 404
    company = jobs[0].company if jobs else a.company_name()
    return Detection(input="", status="found", kind=kind, identifier=ident, company=company, jobs=len(jobs))


def from_text(text: str) -> list[tuple[str, str]]:
    found = []
    for kind, rx in PATTERNS:
        for m in rx.finditer(text):
            ident = m.group(1).strip(".")
            if ident.lower() not in IGNORE_SLUGS and (kind, ident) not in found:
                found.append((kind, ident))
    return found


def _robots_ok(url: str, client: httpx.Client) -> bool:
    parts = urlparse(url)
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = client.get(f"{parts.scheme}://{parts.netloc}/robots.txt")
        if r.status_code >= 400:
            return True
        rp.parse(r.text.splitlines())
        return rp.can_fetch(settings.user_agent, url)
    except httpx.HTTPError:
        return True


def _fetch_page(url: str, transport=None) -> tuple[str, str]:
    """Return (final_url, html) for a careers page, respecting robots.txt."""
    headers = {"User-Agent": settings.user_agent, "Accept": "text/html,application/xhtml+xml"}
    with httpx.Client(timeout=12, follow_redirects=True, headers=headers, transport=transport) as c:
        if not _robots_ok(url, c):
            raise SourceError("this site's robots.txt doesn't allow automated access")
        r = c.get(url)
        if r.status_code >= 400:
            raise SourceError(f"the page returned HTTP {r.status_code}")
        return str(r.url), r.text[:1_500_000]


def slugs_for(name: str) -> list[str]:
    base = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|company|technologies|technology|labs|group|hq|ai)\b\.?", "", name.lower())
    words = re.findall(r"[a-z0-9]+", base) or re.findall(r"[a-z0-9]+", name.lower())
    full = re.findall(r"[a-z0-9]+", name.lower())
    out = ["".join(words), "-".join(words), "".join(full), "-".join(full)]
    return [s for s in dict.fromkeys(out) if len(s) >= 2]


def detect(entry: str, transport=None) -> Detection:
    entry = (entry or "").strip()
    d = Detection(input=entry, status="not_found")
    if not entry:
        d.message = "empty line"
        return d
    is_url = bool(re.match(r"^(https?://|www\.)", entry, re.I)) or bool(re.search(r"\.[a-z]{2,}(/|$)", entry, re.I)) and " " not in entry
    if is_url:
        url = entry if entry.lower().startswith("http") else "https://" + entry
        wd = workday_parse(url)
        if wd:
            return _workday_hit(entry, wd, transport) or Detection(entry, "not_found", message="That Workday site didn't respond with any jobs.")
        cl = careers_link(url)
        if cl:
            name = next((v[2] for v in CUSTOM_BY_NAME.values() if v[0] == cl[0] and v[1] == cl[1]), "")
            hit = _connector_hit(entry, cl[0], cl[1], name, transport)
            if hit:
                return hit
        for name, rx in UNSUPPORTED:
            if rx.search(url):
                d.status, d.message = "unsupported", f"{name} career sites have no public job feed — not supported."
                return d
        cands = from_text(url)
        page_note = ""
        if not cands:
            try:
                final, html = _fetch_page(url, transport)
                for name, rx in UNSUPPORTED:
                    if rx.search(final) or rx.search(html[:400_000]):
                        d.status, d.message = "unsupported", f"This company uses {name}, which has no public job feed — not supported."
                        return d
                wd = workday_parse(final) or workday_parse(html)
                if wd:
                    hit = _workday_hit(entry, wd, transport)
                    if hit:
                        return hit
                cl = careers_link(final) or careers_link(html)
                if cl:
                    hit = _connector_hit(entry, cl[0], cl[1], "", transport)
                    if hit:
                        return hit
                cands = from_text(final + "\n" + html)
                if not cands:
                    # follow one level of "careers"/"jobs" links on the page
                    for href in re.findall(r'href=["\']([^"\']+)["\']', html)[:400]:
                        if re.search(r"career|jobs|openings|join", href, re.I):
                            try:
                                f2, h2 = _fetch_page(urljoin(final, href), transport)
                                cands = from_text(f2 + "\n" + h2)
                                if cands:
                                    break
                            except SourceError:
                                continue
            except (SourceError, httpx.HTTPError) as e:
                page_note = f" (couldn't read the page: {e})"
        for kind, ident in cands[:4]:
            hit = probe(kind, ident, transport)
            if hit:
                hit.input = entry
                return hit
        host = urlparse(url).netloc.lower().replace("www.", "")
        name_guess = host.split(".")[0] if host else ""
        if name_guess and not cands:
            hit = _probe_name(name_guess, transport)
            if hit:
                hit.input = entry
                hit.message = "Found by company name (the page itself didn't link a job board)."
                return hit
        d.message = ("Couldn't find this company's job list on that page" + page_note + ". Open the company's careers page, "
                     "click into its job search, and paste that page's link (e.g. a …myworkdayjobs.com or jobs.lever.co address). "
                     "Or type just the company name.")
        return d
    key = re.sub(r"[^a-z]", "", entry.lower())
    if key in CUSTOM_BY_NAME:
        kind, ident, company = CUSTOM_BY_NAME[key]
        hit = _connector_hit(entry, kind, ident, company, transport)
        if hit:
            return hit
    if key in KNOWN_WORKDAY:
        hit = _workday_hit(entry, KNOWN_WORKDAY[key], transport)
        if hit:
            return hit
    if key in IN_HOUSE:
        return Detection(entry, "found", kind="jsearch", identifier=IN_HOUSE[key], company=IN_HOUSE[key], jobs=0,
                         message="Has its own careers site with no public feed — JobPilot follows it through Google Jobs "
                                 "(needs your free JSearch key in Settings → Connections).")
    hit = _probe_name(entry, transport)
    if hit:
        hit.input = entry
        if hit.kind in ("ashby", "lever", "recruitee"):
            hit.company = entry  # these feeds don't carry the company's display name
        return hit
    best = None
    for ident in workday_discover(entry, transport)[:3]:
        hit = _workday_hit(entry, ident, transport)
        if hit and (best is None or hit.jobs > best.jobs):
            best = hit
    if best:
        best.company = entry
        return best
    # last resort: Google Jobs lists postings from almost every employer
    return Detection(entry, "found", kind="jsearch", identifier=entry.strip()[:120], company=entry.strip()[:120], jobs=0,
                     message="No public job feed found for this name — JobPilot will follow it through Google Jobs (needs your "
                             "free JSearch key). Pasting the company's job-search link may find a direct feed instead.")


AMBIGUOUS = {"workable", "recruitee", "smartrecruiters", "greenhouse"}  # feeds that report a company name we can check


def _same_company(query: str, found: str) -> bool:
    q = set(re.findall(r"[a-z0-9]+", query.lower())) - {"inc", "llc", "ltd", "corp", "the", "co", "ai", "labs", "health", "hq"}
    f = set(re.findall(r"[a-z0-9]+", found.lower()))
    return bool(q) and q <= f


def _connector_hit(entry: str, kind: str, ident: str, company: str, transport=None) -> Optional[Detection]:
    from . import ADAPTERS

    try:
        a = ADAPTERS[kind](ident, transport=transport, sleep=lambda s: None)
        a.timeout_s, a.detail_limit, a.queries = 12, 0, ["software engineer"]
        a.display = company
        jobs = a.fetch()
    except Exception:
        return None
    if not jobs:
        return None
    return Detection(entry, "found", kind=kind, identifier=ident, company=company or a.company_name(), jobs=len(jobs),
                     message="Company careers site — JobPilot searches it for your target titles once a day.")


def _workday_hit(entry: str, ident: str, transport=None) -> Optional[Detection]:
    from .workday import WorkdayAdapter

    try:
        a = WorkdayAdapter(ident, transport=transport, sleep=lambda s: None)
        a.timeout_s, a.detail_limit = 10, 0
        jobs = a.fetch()
    except Exception:
        return None
    if not jobs:
        return None
    name = entry if not re.match(r"^(https?://|www\.)", entry, re.I) else a.company_name()
    return Detection(entry, "found", kind="workday", identifier=ident, company=name, jobs=len(jobs),
                     message="Workday careers site — JobPilot searches it for your target titles once a day.")


def _probe_name(name: str, transport=None) -> Optional[Detection]:
    """Guess the board slug from a company name. Only boards with open roles count, and on platforms
    that answer for any slug the company name returned must match the one typed."""
    for slug in slugs_for(name)[:4]:
        for kind in PROBE_ORDER:
            ident = slug[:1].upper() + slug[1:] if kind == "smartrecruiters" else slug
            hit = probe(kind, ident, transport)
            if not hit or hit.jobs == 0:
                continue
            if kind in AMBIGUOUS and not _same_company(name, hit.company):
                continue
            return hit
    return None


def detect_many(entries: list[str], transport=None) -> list[Detection]:
    entries = [e.strip() for e in entries if e.strip()][:60]
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(lambda e: detect(e, transport), entries))
