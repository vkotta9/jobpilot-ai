"""Jibe (AMD) and Avature (Lenovo, Deloitte) connectors, and company-name mapping."""
import httpx

from app.services.sources import ADAPTERS
from app.services.sources.bigtech import parse_link
from app.services.sources.detect import CUSTOM_BY_NAME, IN_HOUSE, KNOWN_WORKDAY

LONG = "Design and build GPU software. " * 20


def _jibe(req: httpx.Request) -> httpx.Response:
    if req.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nAllow: /\n")
    assert req.url.path == "/api/jobs"
    return httpx.Response(200, json={"jobs": [
        {"data": {"req_id": "84257", "slug": "84257", "title": "Software Engineer", "description": f"<p>{LONG}</p>",
                  "city": "AUSTIN", "state": "Texas", "country": "United States", "posted_date": "2026-10-20T10:00:00+0000",
                  "apply_url": "https://careers.amd.com/careers-home/jobs/84257"}},
        {"data": {"req_id": "9", "title": "", "description": ""}},
    ]})


def test_jibe_adapter_reads_listing_with_descriptions():
    a = ADAPTERS["jibe"]("careers.amd.com", transport=httpx.MockTransport(_jibe), sleep=lambda s: None)
    a.queries = ["software engineer"]
    jobs = a.fetch()
    assert len(jobs) == 1
    j = jobs[0]
    assert j.company == "AMD" and j.location == "Austin, Texas, United States"
    assert len(j.description_text) > 400 and j.url.endswith("/84257") and j.posted_at.year == 2026


LISTING = """<h3><a href="https://jobs.lenovo.com/en_US/careers/JobDetail/Software-Engineer/82492">Software Engineer - Cloud</a></h3>
<span class="paragraph">IT</span><div class="article__header__text__subtitle"><span>United States, North Carolina, Morrisville</span><br>
<span>Req #: WD00106663</span><br><span>Posted 09-Oct-2026</span></div>
<a href="https://jobs.lenovo.com/en_US/careers/JobDetail/Software-Engineer/82492">Apply</a>"""
DETAIL = f"""<article><div class="article__content__view__field"><div class="article__content__view__field__value"><div><p>{LONG}</p></div>
<p>Qualifications</p><ul><li>Python</li></ul></div></div></article>"""


def _avature(req: httpx.Request) -> httpx.Response:
    p = req.url.path
    if p == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nDisallow: /*qtvc=\n")
    if "/SearchJobs/" in p:
        return httpx.Response(200, text=LISTING if "jobOffset" not in str(req.url) else "")
    if "/JobDetail/" in p:
        return httpx.Response(200, text=DETAIL)
    return httpx.Response(404)


def test_avature_adapter_parses_search_and_detail():
    a = ADAPTERS["avature"]("jobs.lenovo.com/en_US/careers", transport=httpx.MockTransport(_avature), sleep=lambda s: None)
    a.queries = ["software engineer"]
    jobs = a.fetch()
    assert len(jobs) == 1
    j = jobs[0]
    assert j.external_id == "82492" and j.title == "Software Engineer - Cloud" and j.company == "Lenovo"
    assert j.location == "United States, North Carolina, Morrisville" and j.posted_at.day == 9
    assert "Qualifications" in j.description_text and "Python" in j.description_text


def test_requested_companies_have_direct_feeds_or_google_jobs():
    assert CUSTOM_BY_NAME["amd"][0] == "jibe" and CUSTOM_BY_NAME["lenovo"][0] == "avature"
    assert CUSTOM_BY_NAME["jpmorganchase"][0] == "oraclehcm" and CUSTOM_BY_NAME["morganstanley"][0] == "eightfold"
    assert KNOWN_WORKDAY["accenture"].startswith("accenture|wd103") and KNOWN_WORKDAY["toyota"] == "toyota|wd503|TMNA"
    assert "accenture" not in IN_HOUSE and IN_HOUSE["goldmansachs"] == "Goldman Sachs" and IN_HOUSE["wipro"] == "Wipro"
    assert parse_link("https://careers.amd.com/careers-home/jobs/1") == ("jibe", "careers.amd.com")
    assert parse_link("https://jobs.lenovo.com/en_US/careers/JobDetail/x/1") == ("avature", "jobs.lenovo.com/en_US/careers")
