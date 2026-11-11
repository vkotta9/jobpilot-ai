"""Hacker News "Ask HN: Who is hiring?" — the monthly thread where thousands of startups post roles.

Free and keyless: the public HN search API (hn.algolia.com) returns the newest thread and its comments in two
requests. Each top-level comment is one company's post; by convention its first line is
"Company | Role(s) | Location | REMOTE/ONSITE | Salary | URL". JobPilot keeps posts with a role matching your
target titles (and role tracks), one job per post, and links back to the post on news.ycombinator.com.
"""
from __future__ import annotations

import html
import re
from typing import Optional

from ..textutil import strip_html
from .base import NormalizedJob, SourceError
from .keyword import KeywordAdapter, _dt, title_matches

API = "https://hn.algolia.com/api/v1"
_ROLE_WORDS = re.compile(r"\b(engineer|developer|scientist|designer|manager|lead|architect|analyst|researcher|sre|devops|"
                         r"swe|sde|founding|intern|head of|director|specialist|administrator|recruiter|product|marketing|"
                         r"sales|operations|ops|account|writer|technician)s?\b", re.I)
_LOC_WORDS = re.compile(r"\b(remote|onsite|on-site|hybrid|in[- ]office|relocation|visa|usa?|united states|europe|eu|uk|"
                        r"canada|anywhere|worldwide|global|timezones?|new york|nyc|san francisco|sf|bay area|india|"
                        r"seattle|boston|austin|los angeles|chicago|denver|london|berlin|toronto|paris|amsterdam)\b", re.I)
_STATE = re.compile(r"(?:^|,\s*)(?!AI\b|ML\b|UI\b|UX\b|QA\b|IT\b)[A-Z]{2}\b")  # ", CA" / "NY" (case-sensitive)
_TECH = re.compile(r"\b(python|typescript|javascript|react|rust|golang|java|kotlin|swift|postgres|aws|kubernetes|django|rails|node)\b", re.I)
_PAY = re.compile(r"[$€£]\s?\d|\d+\s?k\b|salary|equity|compensation", re.I)
_URL = re.compile(r"https?://\S+|\b[\w-]+\.(?:com|io|ai|co|dev|org|net|app|so|xyz|tech)\b(?:/\S*)?", re.I)


def _header_parts(text: str) -> list[str]:
    """The pipe-separated first line of a post (the convention); [] if the post doesn't follow it."""
    first = text.strip().split("\n", 1)[0]
    parts = [p.strip() for p in re.split(r"\s*[|•·]\s*", first) if p.strip()]
    return parts if len(parts) >= 2 else []


def _company(part: str) -> str:
    c = re.sub(r"\((?:YC|yc)[^)]*\)|\([^)]*\)", "", part)
    c = _URL.sub("", c).strip(" -–—:,")
    return c[:120]


def _split_roles(part: str) -> list[str]:
    roles = [r.strip(" -–—*.:") for r in re.split(r",|;|/(?![^()]*\))|\band\b|&", part) if r.strip()]
    return [r for r in roles if 3 <= len(r) <= 90]


def parse_post(raw_html: str) -> Optional[dict]:
    """{'company', 'roles', 'location', 'remote', 'url'} for a hiring post, or None if it isn't one."""
    text = strip_html(html.unescape(raw_html or "").replace("<p>", "\n<p>"))
    if len(text) < 40:
        return None
    parts = _header_parts(text)
    if not parts:
        return None
    company = _company(parts[0])
    if not company or len(company.split()) > 8:
        return None
    roles, locs = [], []
    if len(parts) >= 3 and _company(parts[1]).lower() == company.lower():  # "Bikky | Bikky | Senior SWE | …"
        parts = parts[:1] + parts[2:]
    for p in parts[1:]:
        if (_URL.search(p) and len(p.split()) <= 2) or (_PAY.search(p) and not _ROLE_WORDS.search(p)):
            continue
        if _ROLE_WORDS.search(p):
            roles += _split_roles(p)
        elif (_LOC_WORDS.search(p) or _STATE.search(p)) and len(_TECH.findall(p)) < 2:
            locs.append(_URL.sub("", p).strip(" ;,"))
    # roles listed in the body ("- Senior Backend Engineer", "Hiring: ML Engineer")
    for line in text.split("\n")[1:40]:
        line = re.sub(r"\[\d+\]", "", line).strip(" -*•\t")
        line = re.split(r"\s+[•|·]\s+|\s+[-–—]\s+(?=[A-Z])", line)[0].strip()  # "Role • Location • Full time" -> "Role"
        if 5 <= len(line) <= 70 and _ROLE_WORDS.search(line) and not line.endswith((".", ":", "?")) and not _URL.search(line):
            roles += _split_roles(line)
    hrefs = re.findall(r'href="([^"]+)"', html.unescape(raw_html or ""))
    url = next((h for h in hrefs if h.startswith("http") and "ycombinator.com" not in h), "") or \
        next((m for p in parts for m in re.findall(r"https?://[^\s|]+", p)), "")
    location = "; ".join(locs)[:200]
    head = " ".join(parts).lower()
    remote = bool(re.search(r"\bremote\b", head)) and not re.search(r"\bno remote\b|\bnot remote\b", head)
    return {"company": company, "roles": list(dict.fromkeys(roles)), "location": location, "remote": remote,
            "url": url, "text": text}


def _overlap(role: str, terms: list[str]) -> float:
    """How closely a role matches your best-fitting title (share of that title's words in the role)."""
    words = set(re.findall(r"[a-z0-9+#]+", role.lower()))
    best = 0.0
    for t in terms:
        tw = set(re.findall(r"[a-z0-9+#]+", t.lower()))
        if tw:
            best = max(best, len(tw & words) / len(tw))
    return best


class HNHiringAdapter(KeywordAdapter):
    kind = "hn_hiring"
    label = "Hacker News “Who is hiring?” (startups)"
    docs_url = "https://hn.algolia.com/api"
    min_interval_hours = 12  # the thread is monthly; new posts trickle in during the first days

    def latest_thread(self) -> tuple[str, str]:
        data = self._get_json(f"{API}/search_by_date", params={"tags": "story,author_whoishiring", "hitsPerPage": 10})
        for h in (data or {}).get("hits", []):
            if "who is hiring" in (h.get("title") or "").lower():
                return str(h["objectID"]), h["title"]
        raise SourceError("hn_hiring: couldn't find this month's “Who is hiring?” thread.")

    def fetch(self) -> list[NormalizedJob]:
        self._need_queries()
        story_id, title = self.latest_thread()
        data = self._get_json(f"{API}/search", params={"tags": f"comment,story_{story_id}", "hitsPerPage": 1000})
        terms = self.title_terms or self.queries
        out: dict[str, NormalizedJob] = {}
        for c in (data or {}).get("hits", []):
            if str(c.get("parent_id")) != story_id:  # replies to posts aren't posts
                continue
            post = parse_post(c.get("comment_text") or "")
            if not post:
                continue
            hits = [r for r in post["roles"] if title_matches(r, terms)]
            if not hits:
                continue
            match = max(hits, key=lambda r: _overlap(r, terms))
            others = [r for r in post["roles"] if r != match][:6]
            hn_url = f"https://news.ycombinator.com/item?id={c['objectID']}"
            desc = post["text"] + (f"\n\nAlso hiring: {', '.join(others)}" if others else "") + \
                f"\n\n(Posted in Hacker News “{title}” — {hn_url})"
            out[str(c["objectID"])] = NormalizedJob(
                external_id=str(c["objectID"]), title=match[:200], company=post["company"],
                location=post["location"] or ("Remote" if post["remote"] else ""),
                remote_type="remote" if post["remote"] else ("onsite" if re.search(r"onsite|on-site", post["location"], re.I) else "unknown"),
                description_text=desc, posted_at=_dt(c.get("created_at")),
                url=hn_url, apply_url=post["url"] or hn_url, department="Startup (Hacker News)")
        return list(out.values())
