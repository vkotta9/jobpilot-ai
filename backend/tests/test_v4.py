"""Big-tech careers connectors: Amazon, Eightfold/Microsoft (PCSX), Google, Apple, Oracle HCM, link parsing."""
import json

from app.services.sources import ADAPTERS
from app.services.sources.bigtech import parse_link

from .test_v3 import run

ROBOTS_OK = (200, "User-agent: *\nAllow: /\n")


def test_amazon_search_json():
    jobs = run("amazon", {"https://www.amazon.jobs/robots.txt": ROBOTS_OK,
                          "https://www.amazon.jobs/en/search.json": (200, {"jobs": [{
                              "id_icims": "123", "title": "Software Development Engineer", "normalized_location": "Seattle, WA, USA",
                              "description": "<p>Build things</p>", "basic_qualifications": "Python", "job_path": "/en/jobs/123/sde",
                              "posted_date": "October 20, 2026"}]})}, ident="amazon")
    assert len(jobs) == 1 and jobs[0].url == "https://www.amazon.jobs/en/jobs/123/sde"
    assert "Basic qualifications" in jobs[0].description_text and jobs[0].posted_at.year == 2026


def test_microsoft_falls_back_to_pcsx_when_v2_refused():
    host = "https://apply.careers.microsoft.com"
    jobs = run("microsoft", {
        host + "/robots.txt": ROBOTS_OK,
        host + "/api/apply/v2/jobs": (403, {}),
        host + "/api/pcsx/search": (200, {"data": {"positions": [{
            "id": 1970393557042245, "name": "Software Engineer II", "standardizedLocations": ["Redmond, WA, US"],
            "postedTs": 1792809886, "department": "Azure", "workLocationOption": "hybrid", "positionUrl": "/careers/job/1970393557042245"}]}}),
        host + "/api/pcsx/position_details": (200, {"data": {"jobDescription": "<p>Qualifications: C#, distributed systems</p>",
                                                              "publicUrl": "https://jobs.careers.microsoft.com/global/en/job/200062483"}}),
    }, ident="microsoft")
    assert len(jobs) == 1
    j = jobs[0]
    assert j.company == "Microsoft" and j.remote_type == "hybrid" and "distributed systems" in j.description_text
    assert j.url.endswith("/200062483") and j.location == "Redmond, WA, US"


def test_robots_disallow_blocks_connector():
    import pytest
    from app.services.sources import SourceError

    with pytest.raises(SourceError, match="robots"):
        run("amazon", {"https://www.amazon.jobs/robots.txt": (200, "User-agent: *\nDisallow: /\n")}, ident="amazon")


def test_google_results_and_detail_pages():
    base = "https://www.google.com/about/careers/applications/jobs/results"
    results = '<a href="jobs/results/112892793986130630-senior-software-engineer-cloud">x</a>'
    detail = ("<html><title>Senior Software Engineer, Cloud — Google Careers</title><body>place Sunnyvale, CA, USA\n"
              "<h3>Minimum qualifications:</h3><ul><li>Bachelor's degree</li><li>5 years with Go</li></ul>"
              "Google is proud to be an equal opportunity workplace</body></html>")
    jobs = run("google", {"https://www.google.com/robots.txt": ROBOTS_OK,
                          base + "/112892793986130630": (200, detail), base: (200, results)}, ident="google")
    assert len(jobs) == 1
    j = jobs[0]
    assert j.title == "Senior Software Engineer, Cloud" and "5 years with Go" in j.description_text
    assert "equal opportunity" not in j.description_text


def _apple_page(obj):
    return "<script>window.__staticRouterHydrationData = JSON.parse(" + json.dumps(json.dumps(obj)) + ");</script>"


def test_apple_hydration_data():
    search = {"loaderData": {"search": {"searchResults": [{
        "positionId": "200570000", "postingTitle": "Software Engineer, Siri", "transformedPostingTitle": "software-engineer-siri",
        "postDateInGMT": "2026-10-20T00:00:00Z", "locations": [{"name": "Cupertino", "countryName": "United States"}],
        "team": {"teamName": "Software and Services"}}]}}}
    detail = {"loaderData": {"jobDetails": {"jobsData": {"jobSummary": "Work on Siri.", "minimumQualifications": "<li>Swift</li>"}}}}
    jobs = run("apple", {"https://jobs.apple.com/robots.txt": ROBOTS_OK,
                         "https://jobs.apple.com/en-us/details/": (200, _apple_page(detail)),
                         "https://jobs.apple.com/en-us/search": (200, _apple_page(search))}, ident="apple")
    assert len(jobs) == 1
    j = jobs[0]
    assert j.location == "Cupertino, United States" and "Swift" in j.description_text and j.department == "Software and Services"


def test_parse_link_maps_big_tech_sites():
    assert parse_link("https://www.amazon.jobs/en/search?base_query=sde")[0] == "amazon"
    assert parse_link("https://careers.microsoft.com/v2/global/en/home.html")[0] == "microsoft"
    assert parse_link("https://www.google.com/about/careers/applications/jobs/results")[0] == "google"
    assert parse_link("https://jobs.apple.com/en-us/search")[0] == "apple"
    assert set(["amazon", "google", "microsoft", "apple", "eightfold", "oraclehcm"]) <= set(ADAPTERS)


def test_top_tech_catalog_and_endpoint(client):
    from app.services.sources.catalog import TOP_TECH

    from .conftest import make_user

    assert len(TOP_TECH) == 100 and len({t["company"] for t in TOP_TECH}) == 100
    assert all(t["kind"] in ADAPTERS for t in TOP_TECH)
    direct = [t for t in TOP_TECH if t["via"] == "direct"]
    assert len(direct) >= 60 and {"Apple", "Microsoft", "Google", "Amazon", "NVIDIA"} <= {t["company"] for t in direct}
    assert next(t for t in TOP_TECH if t["company"] == "Meta")["kind"] == "jsearch"
    h, _ = make_user(client)
    r = client.get("/api/companies/top-tech", headers=h).json()
    assert r["jsearch_connected"] is False and len(r["companies"]) == 100
    oracle = next(t for t in TOP_TECH if t["company"] == "Oracle")
    out = client.post("/api/companies/follow", headers=h, json={"run_now": False, "items": [
        {"kind": oracle["kind"], "identifier": oracle["identifier"], "company": "Oracle"}]}).json()
    assert out["added"] == 1
    src = next(s for s in client.get("/api/companies", headers=h).json() if s["kind"] == "oraclehcm")
    assert src["identifier"] == "eeho.fa.us2.oraclecloud.com|CX_45001"  # case kept: the site number is case-sensitive
    assert next(c for c in client.get("/api/companies/top-tech", headers=h).json()["companies"] if c["company"] == "Oracle")["following"]


def test_following_many_companies_runs_in_background(client, monkeypatch):
    import time

    from app.api import companies as api_companies

    from .conftest import make_user

    calls = []
    monkeypatch.setattr(api_companies, "run_source", lambda db, src: calls.append(src.identifier) or {"new": 0, "changed_job_ids": []})
    h, _ = make_user(client)
    items = [{"kind": "greenhouse", "identifier": f"bgco{i}", "company": f"Co {i}"} for i in range(10)]
    out = client.post("/api/companies/follow", headers=h, json={"items": items}).json()
    assert out["added"] == 10 and out.get("background") is True
    for _ in range(50):
        if len(calls) == 10:
            break
        time.sleep(0.05)
    assert sorted(calls) == sorted(i["identifier"] for i in items)


def test_jsearch_company_follow_checked_weekly():
    js = ADAPTERS["jsearch"]
    assert js.interval_for("auto") == 12 and js.interval_for("Meta") == 168
    assert ADAPTERS["greenhouse"].interval_for("stripe") == 0


def test_detect_uses_verified_top_tech_entries():
    from app.services.sources import detect as det

    d = det.detect("Meta")
    assert d.status == "found" and d.kind == "jsearch"
    d = det.detect("eBay")
    assert d.kind == "jsearch"  # its Workday tenant is a subsidiary's site, so don't guess
