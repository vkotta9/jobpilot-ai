"""More company careers platforms.

* Jibe (iCIMS) sites — e.g. careers.amd.com — have a public JSON listing at /api/jobs.
* Avature sites — e.g. jobs.lenovo.com, apply.deloitte.com — list jobs on /<locale>/careers/SearchJobs pages.

Both check robots.txt first (and Jibe's crawl-delay is respected between pages).
"""
from __future__ import annotations

import html as _html
import re
from datetime import datetime
from typing import Optional

import httpx

from ..textutil import strip_html
from .base import NormalizedJob, SourceError, infer_remote_type
from .bigtech import _CareersSiteAdapter, _dt

BROWSER_UA = "Mozilla/5.0 (compatible; JobPilotAI/0.1; personal job search)"


class JibeAdapter(_CareersSiteAdapter):
    """iCIMS Jibe careers sites (identifier: host, e.g. careers.amd.com)."""

    kind = "jibe"
    docs_url = "https://www.icims.com/"

    def company_name(self) -> str:
        return self.display or self.identifier.split(".")[-2].upper()

    def fetch(self) -> list[NormalizedJob]:
        base = f"https://{self.identifier}/api/jobs"
        self._allowed(base)
        rows: dict[str, dict] = {}
        for qi, q in enumerate(self._searches()):
            for page in (1, 2):
                if qi or page > 1:
                    self._sleep(2)
                data = self._get_json(base, params={"page": page, "limit": 50, "keywords": q, "sortBy": "posted_date", "descending": "true"})
                items = (data or {}).get("jobs") or []
                for it in items:
                    d = it.get("data") or it
                    if d.get("req_id") or d.get("slug"):
                        rows[str(d.get("req_id") or d.get("slug"))] = d
                if len(items) < 50:
                    break
        out = []
        for rid, d in rows.items():
            loc = ", ".join(x for x in [d.get("city", "").title() if d.get("city", "").isupper() else d.get("city", ""), d.get("state"), d.get("country")] if x) \
                or d.get("location_name", "")
            url = d.get("apply_url") or f"https://{self.identifier}/careers-home/jobs/{d.get('slug') or rid}"
            desc = strip_html((d.get("description") or "") + "\n" + (d.get("qualifications") or "") + "\n" + (d.get("responsibilities") or ""))
            out.append(NormalizedJob(
                external_id=rid, title=(d.get("title") or "").strip(), company=self.company_name(), location=loc,
                remote_type=infer_remote_type(loc, d.get("title", "")), employment_type=d.get("employment_type", "") or "",
                department=", ".join(c.get("name", "") for c in d.get("categories") or [] if isinstance(c, dict)),
                description_text=desc, posted_at=_dt(d.get("posted_date") or d.get("create_date")), url=url, apply_url=url))
        return [n for n in out if n.title]


class AvatureAdapter(_CareersSiteAdapter):
    """Avature careers sites (identifier: host/locale/careers, e.g. jobs.lenovo.com/en_US/careers)."""

    kind = "avature"
    docs_url = "https://www.avature.net/"
    PER_PAGE = 10

    def company_name(self) -> str:
        return self.display or self.identifier.split("/")[0].split(".")[-2].title()

    def _page(self, url: str, params: Optional[dict] = None) -> str:
        with httpx.Client(timeout=self.timeout_s or 25, transport=self._transport, follow_redirects=True,
                          headers={"User-Agent": BROWSER_UA, "Accept": "text/html"}) as c:
            r = c.get(url, params=params)
        if r.status_code >= 400:
            raise SourceError(f"avature: page returned HTTP {r.status_code}", status=r.status_code)
        return r.text

    LIST_RX = re.compile(r'href="(https?://[^"]+/JobDetail/([^"/]+)/(\d+))"[^>]*>\s*([^<]{3,200}?)\s*</a>(.{0,1800})', re.S)

    def fetch(self) -> list[NormalizedJob]:
        root = "https://" + self.identifier.strip("/")
        self._allowed(root + "/SearchJobs")
        rows: dict[str, dict] = {}
        for q in self._searches():
            for offset in (0, 10, 20, 30):
                page = self._page(f"{root}/SearchJobs/{q.replace(' ', '%20')}", {"jobOffset": offset} if offset else None)
                found = 0
                for url, slug, jid, title, tail in self.LIST_RX.findall(page):
                    t = _html.unescape(re.sub(r"\s+", " ", title)).strip()
                    if jid in rows or t.lower() in ("apply", "apply now", "") or url.startswith("mailto"):
                        continue
                    spans = [_html.unescape(re.sub(r"\s+", " ", x)).strip() for x in re.findall(r"<span[^>]*>\s*([^<]{2,160}?)\s*</span>", tail)]
                    loc = next((x for x in spans if "," in x and not re.match(r"(?i)req|posted", x)), "")
                    posted = next((x[7:] for x in spans if x.lower().startswith("posted ")), "")
                    rows[jid] = {"url": url, "title": t, "location": loc, "posted": posted}
                    found += 1
                if found < self.PER_PAGE - 2:
                    break
        out, done = [], 0
        for jid, r in rows.items():
            desc = ""
            if self._want_detail(r["title"], done, jid):
                try:
                    desc = self.describe(jid, r["url"]) or ""
                    done += 1
                except SourceError:
                    pass
            posted = None
            if r["posted"]:
                for fmt in ("%d-%b-%Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
                    try:
                        posted = datetime.strptime(r["posted"].strip(), fmt)
                        break
                    except ValueError:
                        continue
            out.append(NormalizedJob(external_id=jid, title=r["title"], company=self.company_name(), location=r["location"],
                                     remote_type=infer_remote_type(r["location"], r["title"]), description_text=desc,
                                     posted_at=posted, url=r["url"], apply_url=r["url"]))
        return out

    def describe(self, external_id: str, url: str) -> Optional[str]:
        page = self._page(url)
        # a field's value can hold nested <div>s, so take everything up to the next field (or the article's end)
        vals = [strip_html(v) for v in re.findall(
            r'class="(?:article__content__view__field__value|field-value)[^"]*"[^>]*>(.*?)'
            r'(?=class="article__content__view__field[ "_]|class="field-(?:label|value)|data-map="item-label|</article>|<footer|\Z)', page, re.S)]
        vals = [re.sub(r"<[^>]*$", "", v).strip() for v in vals]
        best = max(vals, key=len) if vals else ""
        if len(best) < 200:  # other Avature templates: the main article body
            m = re.search(r"<article[^>]*>(.*?)</article>", page, re.S)
            best = strip_html(m.group(1)) if m else best
        return best[:20000] or None
