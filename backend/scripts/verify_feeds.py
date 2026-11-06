"""Check that each careers feed belongs to the company it's filed under (run in GitHub Actions).

Input JSON: [{"company", "kind", "identifier", "keywords": [...]}]. For each feed it lists the open roles, opens up to
four postings and checks whether the company's name (any keyword) appears in their text. Writes verify.json.
"""
from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.sources import ADAPTERS  # noqa: E402


def check(item: dict) -> dict:
    out = {**item, "jobs": 0, "described": 0, "hits": 0, "titles": [], "locations": [], "error": ""}
    try:
        a = ADAPTERS[item["kind"]](item["identifier"], sleep=lambda s: None)
        a.timeout_s = 15
        if hasattr(a, "detail_limit"):
            a.detail_limit = 4
        jobs = a.fetch()
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:160]
        return out
    out["jobs"] = len(jobs)
    out["titles"] = [j.title for j in jobs[:4]]
    out["locations"] = [j.location for j in jobs[:4]]
    kws = [k.lower() for k in item["keywords"]]
    for j in jobs:
        text = (j.description_text or "")
        if not text:
            continue
        out["described"] += 1
        low = re.sub(r"\s+", " ", text.lower())
        if any(k in low for k in kws):
            out["hits"] += 1
        if out["described"] >= 4:
            break
    return out


def main() -> None:
    items = json.loads(Path(sys.argv[1]).read_text())
    with ThreadPoolExecutor(max_workers=12) as pool:
        res = list(pool.map(check, items))
    Path(os.getenv("VERIFY_OUT", "verify.json")).write_text(json.dumps(res, indent=1))
    print(sum(1 for r in res if r["hits"]), "of", len(res), "feeds mention their company")


if __name__ == "__main__":
    main()
