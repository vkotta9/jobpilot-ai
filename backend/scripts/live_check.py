"""Call a real job source through its adapter and report how many jobs came back.

Usage: python scripts/live_check.py remotive|muse|greenhouse|lever|site [arg]
Exit code 0 = at least one job (or site healthy), 1 = nothing / error. Used by
.github/workflows/live-check.yml to verify integrations from the internet.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.services.sources import ADAPTERS, SourceError  # noqa: E402


def main() -> int:
    kind = sys.argv[1]
    arg = sys.argv[2] if len(sys.argv) > 2 else ""
    if kind == "site":
        r = httpx.get(arg.rstrip("/") + "/api/health", timeout=120, follow_redirects=True)
        print(r.status_code, r.text[:300])
        print(f"::notice title=site::HTTP {r.status_code} {r.text[:120]}")
        return 0 if r.status_code == 200 and '"status":"ok"' in r.text.replace(" ", "") else 1
    if kind == "timing":
        import time as _t

        rows = []
        base = arg.rstrip("/")
        for rnd in (1, 2, 3):
            for path in ("/api/health", "/", "/static/js/app.js", "/static/js/pages/discover.js", "/api/companies/top-tech"):
                t0 = _t.time()
                try:
                    r = httpx.get(base + path, timeout=180, follow_redirects=True)
                    rows.append(f"r{rnd} {path} {r.status_code} {len(r.content)}B {(_t.time() - t0):.2f}s cache={r.headers.get('cache-control')}"
                                + (f" countryFilter={'countrySel' in r.text}" if path.endswith("discover.js") else ""))
                except Exception as e:  # noqa: BLE001
                    rows.append(f"r{rnd} {path} ERR {type(e).__name__} {(_t.time() - t0):.2f}s")
        try:
            import io as _io, json as _js, zipfile as _zf
            z = _zf.ZipFile(_io.BytesIO(httpx.get(base + "/api/extension/jobpilot-extension.zip", timeout=60).content))
            m = _js.loads(z.read("manifest.json"))
            rows.append(f"extension zip OK: matches={m['content_scripts'][0]['matches']} config={z.read('config.js').decode().strip()}")
        except Exception as e:  # noqa: BLE001
            rows.append(f"extension zip ERROR {e}")
        print("::notice title=timing::" + " || ".join(rows))
        return 0
    if kind == "links":
        from app.services import interview_prep as ip

        urls = {u for _, u in ip.R.values()}
        for sk in ip.SKILLS.values():
            for r in sk["resources"]:
                if not isinstance(r, str):
                    urls.add(r[1])
        urls |= {c["url"] for c in ip.COMPANIES.values() if c.get("url")}
        bad, ok = [], 0
        for u in sorted(urls):
            try:
                r = httpx.get(u, timeout=25, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (JobPilot link check)"})
                if r.status_code < 400 or r.status_code in (403, 429):  # some sites block bots but the page exists
                    ok += 1
                    if r.status_code >= 400:
                        bad.append(f"{u} → {r.status_code} (bot-blocked?)")
                else:
                    bad.append(f"{u} → {r.status_code}")
            except Exception as e:  # noqa: BLE001
                bad.append(f"{u} → {type(e).__name__}")
        print(f"::notice title=links::{ok}/{len(urls)} OK || " + " || ".join(bad))
        return 0
    if kind == "workday":
        from app.services.sources.workday import WorkdayAdapter

        rows = []
        for ident in arg.split(","):
            try:
                a = WorkdayAdapter(ident)
                a.queries = ["Software Engineer"]
                a.title_filter = lambda t: "engineer" in t.lower()
                jobs = a.fetch()
                withdesc = sum(1 for j in jobs if len(j.description_text) > 200)
                rows.append(f"{ident}={len(jobs)} jobs/{sum(1 for j in jobs if 'engineer' in j.title.lower())} match/{withdesc} desc")
            except Exception as e:  # noqa: BLE001
                rows.append(f"{ident}=ERR {str(e)[:60]}")
        for i in range(0, len(rows), 8):
            print("::notice title=workday::" + " | ".join(rows[i:i + 8]))
        return 0
    if kind == "robots":
        import urllib.robotparser
        from urllib.parse import urlparse

        rows = []
        for url in arg.split(","):
            pr = urlparse(url)
            rp = urllib.robotparser.RobotFileParser(f"{pr.scheme}://{pr.netloc}/robots.txt")
            try:
                rp.read()
                rows.append(f"{url} → {'ALLOWED' if rp.can_fetch('JobPilotAI/0.1', url) else 'DISALLOWED'}")
            except Exception as e:  # noqa: BLE001
                rows.append(f"{url} → error {e}")
        print("::notice title=robots::" + " || ".join(rows))
        return 0
    if kind == "probe":
        rows = []
        for url in arg.split(","):
            try:
                r = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": "JobPilotAI/0.1", "Accept": "application/json"})
                rows.append(f"{url[:90]} → {r.status_code} {r.headers.get('content-type','')[:30]} {r.text[:160]!r}")
            except Exception as e:  # noqa: BLE001
                rows.append(f"{url[:90]} → {type(e).__name__}")
        print("::notice title=probe::" + " || ".join(rows))
        return 0
    if kind == "shape":
        import json as _j
        import re as _re

        out = []
        h = {"User-Agent": "JobPilotAI/0.1"}
        r = httpx.get("https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com&query=software%20engineer&location=United%20States&start=0&sort_by=timestamp", headers=h, timeout=20)
        d = r.json().get("data", {})
        p0 = (d.get("positions") or [{}])[0]
        out.append("MS search keys=" + ",".join(sorted(d.keys())) + " pos keys=" + ",".join(sorted(p0.keys())) + " sample=" + _j.dumps({k: p0[k] for k in list(p0)[:14]})[:900])
        pid = p0.get("id")
        for path in [f"/api/pcsx/position_details?position_id={pid}&domain=microsoft.com&hl=en", f"/api/apply/v2/jobs/{pid}?domain=microsoft.com"]:
            rr = httpx.get("https://apply.careers.microsoft.com" + path, headers=h, timeout=20)
            try:
                dd = rr.json()
                dd2 = dd.get("data", dd)
                out.append(f"MS detail {path[:40]} {rr.status_code} keys=" + ",".join(sorted(dd2.keys()))[:600] + " desc=" + str(dd2.get("jobDescription") or dd2.get("job_description") or "")[:200])
            except Exception:
                out.append(f"MS detail {path[:40]} {rr.status_code} {rr.text[:120]!r}")
        g = httpx.get("https://www.google.com/about/careers/applications/jobs/results?q=software%20engineer&location=United%20States", headers={**h, "Accept": "text/html"}, timeout=20, follow_redirects=True)
        html = g.text
        ids = _re.findall(r'jobs/results/(\d{6,})-([a-z0-9-]+)', html)
        h3 = _re.findall(r'<h3[^>]*>([^<]{5,120})</h3>', html)
        out.append(f"GOOGLE {g.status_code} len={len(html)} ids={ids[:3]} h3={h3[:3]} jsonld={'JobPosting' in html} af={'AF_initDataCallback' in html}")
        if ids:
            jp = httpx.get(f"https://www.google.com/about/careers/applications/jobs/results/{ids[0][0]}-{ids[0][1]}", headers={**h, "Accept": "text/html"}, timeout=20, follow_redirects=True)
            t = jp.text
            out.append(f"GOOGLE job {jp.status_code} jsonld={'JobPosting' in t} h2={_re.findall(r'<h2[^>]*>([^<]{3,80})</h2>', t)[:4]} quals={'Minimum qualifications' in t}")
        a = httpx.get("https://jobs.apple.com/en-us/search?search=software%20engineer&sort=newest", headers={**h, "Accept": "text/html"}, timeout=20, follow_redirects=True)
        at = a.text
        out.append(f"APPLE {a.status_code} len={len(at)} details={_re.findall(r'/en-us/details/([0-9-]+)/([a-z0-9-]+)', at)[:3]} hydration={'__staticRouterHydrationData' in at} jsonld={'JobPosting' in at}")
        for i in range(0, len(out), 1):
            print("::notice title=shape::" + out[i][:3000])
        return 0
    if kind == "debug":
        from app.services.sources import ADAPTERS as A

        rows = []
        for spec in arg.split(","):
            k, _, ident = spec.partition("=")
            try:
                a = A[k](ident or k)
                a.queries, a.detail_limit = ["software engineer"], 1
                jobs = a.fetch()
                d2 = ""
                if len(jobs) > 1:
                    try:
                        d2 = a.describe(jobs[-1].external_id, jobs[-1].url) or ""
                    except Exception as e:  # noqa: BLE001
                        d2 = f"ERR {e}"[:80]
                rows.append(f"{k}: {len(jobs)} jobs; first: {jobs[0].title if jobs else '-'} desc={len(jobs[0].description_text) if jobs else 0}; "
                            f"on-demand describe(last)={len(d2) if not d2.startswith('ERR') else d2}")
            except Exception as e:  # noqa: BLE001
                rows.append(f"{k}: ERROR {type(e).__name__}: {str(e)[:200]}")
        print("::notice title=debug::" + " || ".join(rows))
        return 0
    if kind == "detect":
        from app.services.sources.detect import detect

        res = [detect(x).dict() for x in arg.split("|")]
        print("::notice title=detect::" + " | ".join(f"{r['input']} → {r['status']} {r['kind']}:{r['identifier']} ({r['jobs']} jobs) {r['message'][:60]}" for r in res))
        return 0
    ctx = {"queries": ["Software Engineer"], "locations": [], "credentials": {}}
    try:
        cls = ADAPTERS[kind]
        jobs = cls(arg or "auto", context=ctx).fetch() if cls.keyword else cls(arg).fetch()
    except SourceError as e:
        print(f"::error::{kind}: {e}")
        return 1
    print(f"{kind}: {len(jobs)} jobs")
    sample = "; ".join(f"{j.title} @ {j.company} ({len(j.description_text)} chars)" for j in jobs[:2])
    print(f"::notice title={kind}::{len(jobs)} jobs. {sample}")
    for j in jobs[:3]:
        print(f"  - {j.title} @ {j.company} [{j.location}] desc={len(j.description_text)} chars url={j.url[:80]}")
    return 0 if jobs else 1


if __name__ == "__main__":
    raise SystemExit(main())
