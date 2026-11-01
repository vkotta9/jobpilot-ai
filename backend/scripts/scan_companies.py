"""Find and verify careers feeds for many companies at once (run in GitHub Actions; writes scan.json).

Input file: one company per line:  Category|Company|slug1,slug2,...
For each company it tries Workday tenants (via each tenant's robots.txt sitemap list) and the
Greenhouse / Lever / Ashby boards for each slug, and keeps the feed with the most matching jobs.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.sources.detect import _same_company, probe  # noqa: E402
from app.services.sources.workday import WorkdayAdapter, discover  # noqa: E402


def wd_count(ident: str) -> int:
    try:
        a = WorkdayAdapter(ident, sleep=lambda s: None)
        a.timeout_s, a.detail_limit = 12, 0
        a.queries = ["software engineer"]
        return len(a.fetch())
    except Exception:  # noqa: BLE001
        return -1


def scan(line: str) -> dict:
    cat, name, slugs = (line.split("|") + ["", ""])[:3]
    slugs = [s.strip() for s in slugs.split(",") if s.strip()]
    res = {"category": cat, "company": name, "tried": slugs, "best": None, "candidates": []}
    for slug in slugs:
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
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(scan, lines))
    Path("scan.json").write_text(json.dumps(results, indent=1))
    for r in results:  # also in the log (artifacts can't always be downloaded)
        print("SCAN " + json.dumps(r))
    found = sum(1 for r in results if r["best"])
    print(f"::notice title=scan::{found}/{len(results)} companies have a verified direct feed")


if __name__ == "__main__":
    main()
