"""Find and verify careers feeds for many companies at once (run in GitHub Actions; writes scan.json).

Input file: one company per line:  Category|Company|slug1,slug2,...
For each company it tries Workday tenants (via each tenant's robots.txt sitemap list) and the
Greenhouse / Lever / Ashby boards for each slug, and keeps the feed with the most matching jobs.
"""
from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.sources.detect import _fetch_page, _same_company, from_text, probe  # noqa: E402
from app.services.sources.bigtech import parse_link  # noqa: E402
from app.services.sources.workday import WorkdayAdapter, discover  # noqa: E402


def wd_count(ident: str) -> int:
    try:
        a = WorkdayAdapter(ident, sleep=lambda s: None)
        a.timeout_s, a.detail_limit = 12, 0
        q = os.getenv("SCAN_QUERY", "software engineer")  # empty: count every open role
        a.queries = [q] if q else []
        return len(a.fetch())
    except Exception:  # noqa: BLE001
        return -1


def scan(line: str) -> dict:
    cat, name, slugs = (line.split("|", 2) + ["", ""])[:3]
    slugs = [s.strip() for s in slugs.split(",") if s.strip()]
    res = {"category": cat, "company": name, "tried": slugs, "best": None, "candidates": []}
    for slug in slugs:
        if slug.startswith("wd:"):
            ident = slug[3:]
            res["candidates"].append({"kind": "workday", "identifier": ident, "jobs": wd_count(ident)})
            continue
        if slug.startswith(("sr:", "gh:", "lever:", "ashby:")):
            kind, ident = slug.split(":", 1)
            kind = {"sr": "smartrecruiters", "gh": "greenhouse"}.get(kind, kind)
            hit = probe(kind, ident)
            if hit and hit.jobs:
                res["candidates"].append({"kind": kind, "identifier": ident, "jobs": hit.jobs, "reported": hit.company})
            continue
        if slug.startswith("page:"):
            try:
                _, page = _fetch_page(slug[5:])
            except Exception as e:  # noqa: BLE001
                res["candidates"].append({"kind": "page", "identifier": slug[5:], "jobs": 0, "error": str(e)[:80]})
                continue
            links = from_text(page)[:4]
            for m in re.finditer(r"([A-Za-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)", page):
                ident = f"{m.group(1).lower()}|{m.group(2).lower()}|{m.group(3)}"
                if ("workday", ident) not in links and m.group(3).lower() not in ("wday", "assets"):
                    links.append(("workday", ident))
            pl = parse_link(page)
            if pl and pl not in links:
                links.append(pl)
            links = links[:8]
            res["candidates"].append({"kind": "page", "identifier": slug[5:], "jobs": 0, "links": links})
            for kind, ident in links:
                n = wd_count(ident) if kind == "workday" else ((probe(kind, ident) or type("x", (), {"jobs": 0})).jobs)
                res["candidates"].append({"kind": kind, "identifier": ident, "jobs": n})
            continue
        try:
            idents = discover(slug)[:3]
        except Exception:  # noqa: BLE001
            idents = []
        for ident in idents:
            n = wd_count(ident)
            res["candidates"].append({"kind": "workday", "identifier": ident, "jobs": n})
        for kind in ("greenhouse", "lever", "ashby"):
            hit = probe(kind, slug)
            if hit and hit.jobs and (kind != "greenhouse" or _same_company(name, hit.company) or True):
                res["candidates"].append({"kind": kind, "identifier": slug, "jobs": hit.jobs, "reported": hit.company})
    good = [c for c in res["candidates"] if c["jobs"] and c["jobs"] > 0]
    if good:
        res["best"] = max(good, key=lambda c: c["jobs"])
    return res


def main() -> None:
    lines = [l.strip() for l in Path(sys.argv[1]).read_text().splitlines() if l.strip() and not l.startswith("#")]
    if len(sys.argv) > 3:  # chunk i of n, for parallel runs
        i, n = int(sys.argv[2]), int(sys.argv[3])
        lines = lines[i::n]
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(scan, lines))
    Path(os.getenv("SCAN_OUT", "scan.json")).write_text(json.dumps(results, indent=1))
    for r in results:  # also in the log (artifacts can't always be downloaded)
        print("SCAN " + json.dumps(r))
    found = sum(1 for r in results if r["best"])
    print(f"::notice title=scan::{found}/{len(results)} companies have a verified direct feed")


if __name__ == "__main__":
    main()
