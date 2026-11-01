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


def test_catalog_aliases_and_healthcare_companies():
    from app.services.sources.catalog import TOP_TECH
    from app.services.sources.detect import ALIASES, _top_tech

    idx = _top_tech()
    assert all(v in idx for v in ALIASES.values())
    assert idx[ALIASES["cvs"]]["identifier"] == "cvshealth|wd1|CVS_Health_Careers"
    assert idx[ALIASES["optum"]]["kind"] == "jsearch"  # Taleo: no public feed
    cats = {t["category"] for t in TOP_TECH}
    assert {"Healthcare & pharma", "Insurance", "Retail & consumer", "Telecom & media"} <= cats


def test_detect_uses_catalog_connector_for_oracle_sites():
    from app.services.sources import detect as d

    calls = []
    orig = d._connector_hit
    d._connector_hit = lambda entry, kind, ident, company, transport=None: calls.append((kind, ident)) or d.Detection(entry, "found", kind=kind, identifier=ident, company=company, jobs=3)
    try:
        r = d.detect("Quest Diagnostics")
    finally:
        d._connector_hit = orig
    assert r.kind == "oraclehcm" and calls == [("oraclehcm", "hdox.fa.us6.oraclecloud.com|CX_1")]


def test_every_catalog_company_can_be_followed():
    from app.api.companies import FollowItem
    from app.services.sources.catalog import POPULAR, TOP_TECH

    for c in TOP_TECH + POPULAR:
        FollowItem(kind=c["kind"], identifier=c["identifier"], company=c["company"])  # raises if rejected




def test_follow_all_catalog_companies_at_once(client):
    from app.services.sources.catalog import TOP_TECH
    from .conftest import make_user

    h, _ = make_user(client)
    items = [{"kind": c["kind"], "identifier": c["identifier"], "company": c["company"]} for c in TOP_TECH if c["kind"] != "jsearch"]
    r = client.post("/api/companies/follow", headers=h, json={"run_now": False, "items": items})
    assert r.status_code == 200, r.text
    srcs = {s["identifier"] for s in client.get("/api/companies", headers=h).json()}
    assert "jobs.lenovo.com/en_US/careers" in srcs  # case kept: the locale in the path matters
    top = client.get("/api/companies/top-tech", headers=h).json()["companies"]
    assert next(c for c in top if c["company"] == "Lenovo")["following"]


def test_long_jsearch_values_fit_the_database(client):
    """Postgres rejects values longer than the column (seen with JSearch ids); they're shortened consistently."""
    from app.db import SessionLocal
    from app.models import Job, User
    from app.services.discovery import upsert_job
    from app.services.sources.base import NormalizedJob

    from .conftest import make_user

    _, email = make_user(client)
    long_id = "Ab3_" * 120  # 480 chars
    with SessionLocal() as db:
        uid = db.query(User).filter_by(email=email).one().id
        mk = lambda: NormalizedJob(external_id=long_id, title="Software Engineer " + "x" * 400, company="Samsung " * 40,
                                   location="Austin", department="Eng " * 80, url="https://x.com/" + "a" * 1200,
                                   apply_url="https://x.com/apply", description_text="d")
        job, state = upsert_job(db, uid, None, mk(), "jsearch", False)
        db.commit()
        assert state == "new" and len(job.external_id) <= 200 and len(job.company) <= 200 and job.url == "https://x.com/apply"
        job2, state2 = upsert_job(db, uid, None, mk(), "jsearch", False)
        db.commit()
        assert job2.id == job.id and state2 == "unchanged"
        assert db.query(Job).filter_by(user_id=uid).count() == 1
