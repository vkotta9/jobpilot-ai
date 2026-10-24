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
        return 0 if r.status_code == 200 and '"status":"ok"' in r.text.replace(" ", "") else 1
    ctx = {"queries": ["Software Engineer"], "locations": [], "credentials": {}}
    try:
        cls = ADAPTERS[kind]
        jobs = cls(arg or "auto", context=ctx).fetch() if cls.keyword else cls(arg).fetch()
    except SourceError as e:
        print(f"::error::{kind}: {e}")
        return 1
    print(f"{kind}: {len(jobs)} jobs")
    for j in jobs[:3]:
        print(f"  - {j.title} @ {j.company} [{j.location}] desc={len(j.description_text)} chars url={j.url[:80]}")
    return 0 if jobs else 1


if __name__ == "__main__":
    raise SystemExit(main())
