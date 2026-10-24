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
    ("Workday", re.compile(r"myworkdayjobs\.com|workdayjobs|wd\d+\.myworkday", re.I)),
    ("iCIMS", re.compile(r"icims\.com", re.I)),
    ("Taleo", re.compile(r"taleo\.net", re.I)),
    ("SuccessFactors", re.compile(r"successfactors|sapsf\.", re.I)),
    ("Oracle Cloud", re.compile(r"oraclecloud\.com/hcmUI|fa\.\w+\.oraclecloud", re.I)),
    ("Jobvite", re.compile(r"jobvite\.com", re.I)),
    ("BambooHR", re.compile(r"bamboohr\.com/careers", re.I)),
]
IN_HOUSE = {"google": "Google", "alphabet": "Google", "amazon": "Amazon", "aws": "Amazon", "microsoft": "Microsoft",
            "apple": "Apple", "meta": "Meta", "facebook": "Meta", "netflix": "Netflix", "ibm": "IBM", "oracle": "Oracle",
            "tesla": "Tesla", "nvidia": "NVIDIA (Workday)", "salesforce": "Salesforce (Workday)", "intel": "Intel (Workday)",
            "adobe": "Adobe (Workday)", "uber": "Uber", "linkedin": "LinkedIn", "walmart": "Walmart (Workday)"}
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
    if words:
        out.append(words[0])
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
        d.message = ("No supported job board found on that page" + page_note +
                     ". If the company uses Workday or its own site, it can't be followed automatically.")
        return d
    key = re.sub(r"[^a-z]", "", entry.lower())
    if key in IN_HOUSE:
        d.status = "unsupported"
        d.message = f"{IN_HOUSE[key]} runs its own careers site without a public job feed — not supported."
        return d
    hit = _probe_name(entry, transport)
    if hit:
        hit.input = entry
        if hit.kind in ("ashby", "lever", "recruitee"):
            hit.company = entry  # these feeds don't carry the company's display name
        return hit
    d.message = "Not found on Greenhouse, Lever, Ashby, Workable, Recruitee or SmartRecruiters. Try pasting the company's careers page link."
    return d


AMBIGUOUS = {"workable", "recruitee", "smartrecruiters"}  # these answer for almost any slug


def _same_company(query: str, found: str) -> bool:
    q = set(re.findall(r"[a-z0-9]+", query.lower())) - {"inc", "llc", "ltd", "corp", "the", "co", "ai", "labs", "health", "hq"}
    f = set(re.findall(r"[a-z0-9]+", found.lower()))
    return bool(q) and q <= f


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
