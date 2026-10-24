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
    if kind == "workday":
        from app.services.sources.workday import WorkdayAdapter

        rows = []
        for ident in arg.split(","):
            try:
                a = WorkdayAdapter(ident)
                a.queries, a.detail_limit = ["Software Engineer"], 2
                jobs = a.fetch()
                withdesc = sum(1 for j in jobs if len(j.description_text) > 200)
                rows.append(f"{ident}={len(jobs)} jobs/{withdesc} desc")
            except Exception as e:  # noqa: BLE001
                rows.append(f"{ident}=ERR {str(e)[:60]}")
        for i in range(0, len(rows), 8):
            print("::notice title=workday::" + " | ".join(rows[i:i + 8]))
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
