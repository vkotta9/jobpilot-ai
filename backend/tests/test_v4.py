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
