"""Free job sources, company career boards, link/name detection, following companies."""
import httpx

from app.services.sources import ADAPTERS
from app.services.sources import detect as det
from app.services.sources.catalog import POPULAR

from .conftest import make_user, setup_profile

CTX = {"queries": ["Software Engineer"], "locations": ["New York"], "credentials": {}}


def mock(routes, record=None):
    def handler(req):
        if record is not None:
            record.append(req)
        for prefix, (status, body) in routes.items():
            if str(req.url).startswith(prefix):
                if isinstance(body, str):
                    return httpx.Response(status, text=body, headers={"content-type": "text/html"})
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)


def run(kind, routes, ident="auto", ctx=CTX, record=None):
    cls = ADAPTERS[kind]
    kw = {"context": ctx} if cls.keyword else {}
    return cls(ident, transport=mock(routes, record), sleep=lambda s: None, **kw).fetch()


# ---------------------------------------------------------------- free keyword sources

def test_himalayas_jobicy_arbeitnow():
    hj = run("himalayas", {"https://himalayas.app/jobs/api/search": (200, {"jobs": [
        {"title": "Senior Software Engineer", "companyName": "Acme", "guid": "https://himalayas.app/companies/acme/jobs/sse",
         "applicationLink": "https://acme.com/apply", "description": "<p>Go</p>", "locationRestrictions": ["United States"],
         "pubDate": 1792000000, "minSalary": 150000, "maxSalary": 180000, "currency": "USD", "salaryPeriod": "year"},
        {"title": "Designer", "companyName": "Acme", "guid": "g2"}]})})
    assert len(hj) == 1 and hj[0].apply_url == "https://acme.com/apply" and hj[0].salary_min == 150000
    jj = run("jobicy", {"https://jobicy.com/api/jobs": (200, {"jobs": [
        {"id": 5, "jobTitle": "Software Engineer, Platform", "companyName": "B", "url": "https://jobicy.com/jobs/5",
         "jobGeo": "USA", "jobType": ["full-time"], "jobDescription": "<p>Python</p>", "pubDate": "2026-10-20 10:00:00"}]})})
    assert jj[0].url.startswith("https://jobicy.com") and "Jobicy" in jj[0].description_text
    aj = run("arbeitnow", {"https://www.arbeitnow.com/api/job-board-api": (200, {"data": [
        {"slug": "se-berlin", "title": "Software Engineer (m/w/d)", "company_name": "C", "remote": True, "url": "https://arbeitnow.com/x",
         "description": "<b>Rust</b>", "location": "Berlin", "created_at": 1792000000, "job_types": ["full time"]}], "links": {"next": None}})})
    assert aj[0].remote_type == "remote" and aj[0].posted_at is not None


def test_jsearch_and_usajobs_need_keys_and_parse():
    import pytest
    from app.services.sources import SourceError

    with pytest.raises(SourceError, match="RapidAPI"):
        run("jsearch", {})
    seen = []
    js = run("jsearch", {"https://jsearch.p.rapidapi.com/search": (200, {"data": [
        {"job_id": "abc", "job_title": "Software Engineer", "employer_name": "Initech", "job_city": "New York", "job_state": "NY",
         "job_country": "US", "job_description": "Build things", "job_apply_link": "https://initech.com/apply",
         "job_is_remote": False, "job_min_salary": 120000, "job_max_salary": 150000, "job_salary_period": "YEAR",
         "job_publisher": "LinkedIn", "job_posted_at_datetime_utc": "2026-10-21T00:00:00.000Z"}]})},
             ctx={**CTX, "credentials": {"rapidapi_key": "rk"}}, record=seen)
    assert js[0].salary_max == 150000 and "LinkedIn" in js[0].description_text
    assert seen[0].headers["X-RapidAPI-Key"] == "rk" and "New York" in seen[0].url.params["query"]
    uj = run("usajobs", {"https://data.usajobs.gov/api/search": (200, {"SearchResult": {"SearchResultItems": [
        {"MatchedObjectDescriptor": {"PositionID": "IT-1", "PositionTitle": "IT Specialist (APPSW)", "OrganizationName": "NASA",
                                     "PositionLocationDisplay": "Washington, DC", "PositionURI": "https://www.usajobs.gov/job/1",
                                     "ApplyURI": ["https://www.usajobs.gov/job/1/apply"], "PublicationStartDate": "2026-10-20",
                                     "PositionRemuneration": [{"MinimumRange": "100000", "MaximumRange": "130000", "RateIntervalCode": "PA"}],
                                     "UserArea": {"Details": {"JobSummary": "Develop software", "MajorDuties": ["Code"]}}}}]}})},
             ctx={**CTX, "credentials": {"usajobs_key": "k", "usajobs_email": "me@example.com"}})
    assert uj[0].company == "NASA" and uj[0].salary_min == 100000 and "Develop software" in uj[0].description_text


# ---------------------------------------------------------------- company boards

def test_ashby_workable_recruitee_smartrecruiters():
    a = run("ashby", {"https://api.ashbyhq.com/posting-api/job-board/acme": (200, {"jobs": [
        {"id": "1", "title": "Software Engineer", "location": "NYC", "workplaceType": "Hybrid", "descriptionPlain": "Python",
         "jobUrl": "https://jobs.ashbyhq.com/acme/1", "applyUrl": "https://jobs.ashbyhq.com/acme/1/application", "isListed": True,
         "compensation": {"summaryComponents": [{"compensationType": "Salary", "interval": "1 YEAR", "minValue": 1, "maxValue": 2, "currencyCode": "USD"}]}},
        {"id": "2", "title": "Hidden", "isListed": False, "jobUrl": "u"}]})}, ident="acme")
    assert len(a) == 1 and a[0].remote_type == "hybrid" and a[0].salary_max == 2
    w = run("workable", {"https://apply.workable.com/api/v1/widget/accounts/hf": (200, {"name": "Hugging Face", "jobs": [
        {"shortcode": "AB1", "title": "ML Engineer", "url": "https://apply.workable.com/hf/j/AB1", "full_description": "<p>ML</p>",
         "locations": [{"city": "Paris", "country": "France", "telecommuting": True}], "published_on": "2026-10-01"}]})}, ident="hf")
    assert w[0].company == "Hugging Face" and w[0].remote_type == "remote"
    r = run("recruitee", {"https://acme.recruitee.com/api/offers/": (200, {"offers": [
        {"id": 9, "title": "Backend Developer", "description": "<p>Elixir</p>", "requirements": "<p>3 years</p>",
         "location": "Amsterdam", "careers_url": "https://acme.recruitee.com/o/backend", "published_at": "2026-10-01 10:00:00 UTC"}]})}, ident="acme")
    assert r[0].url.endswith("/o/backend") and "Elixir" in r[0].description_text
    calls = []
    s = run("smartrecruiters", {"https://api.smartrecruiters.com/v1/companies/Canva/postings/p1": (200, {"jobAd": {"sections": {
        "jobDescription": {"text": "<p>Build Canva</p>"}}}}),
        "https://api.smartrecruiters.com/v1/companies/Canva/postings": (200, {"content": [
            {"id": "p1", "name": "Software Engineer", "company": {"name": "Canva"}, "location": {"city": "Austin", "country": "us"},
             "releasedDate": "2026-10-01T00:00:00.000Z"}], "totalFound": 1})}, ident="Canva", record=calls)
    assert s[0].company == "Canva" and "Build Canva" in s[0].description_text


# ---------------------------------------------------------------- detection

def test_detect_parses_links_and_rejects_unsupported():
    assert det.from_text("https://job-boards.greenhouse.io/stripe/jobs/1") == [("greenhouse", "stripe")]
    assert det.from_text("https://jobs.lever.co/palantir") == [("lever", "palantir")]
    assert ("ashby", "openai") in det.from_text("<a href='https://jobs.ashbyhq.com/openai'>")
    assert det.detect("https://acme.wd1.myworkdayjobs.com/careers").status == "unsupported"
    assert det.detect("Google").status == "unsupported"


def test_detect_from_careers_page_and_robots():
    routes = {
        "https://acme.example/robots.txt": (200, "User-agent: *\nAllow: /"),
        "https://acme.example/careers": (200, '<script src="https://boards.greenhouse.io/embed/job_board/js?for=acmeco"></script>'),
        "https://boards-api.greenhouse.io/v1/boards/acmeco/jobs": (200, {"jobs": [{"id": 1, "title": "Engineer", "absolute_url": "u"}]}),
        "https://boards-api.greenhouse.io/v1/boards/acmeco": (200, {"name": "Acme Co"}),
    }
    d = det.detect("https://acme.example/careers", transport=mock(routes))
    assert d.status == "found" and (d.kind, d.identifier, d.company, d.jobs) == ("greenhouse", "acmeco", "Acme Co", 1)
    blocked = {"https://nope.example/robots.txt": (200, "User-agent: *\nDisallow: /")}
    d2 = det.detect("https://nope.example/careers", transport=mock(blocked))
    assert d2.status == "not_found" and "robots.txt" in d2.message


def test_detect_by_name_requires_open_roles_and_matching_company():
    routes = {
        # workable answers for any slug — wrong company name must be rejected
        "https://apply.workable.com/api/v1/widget/accounts/zorbo": (200, {"name": "Some Other Firm", "jobs": [{"shortcode": "x", "title": "T"}]}),
        "https://api.lever.co/v0/postings/zorbo": (200, []),  # exists but no openings → keep looking
    }
    assert det.detect("Zorbo", transport=mock(routes)).status == "not_found"
    routes["https://apply.workable.com/api/v1/widget/accounts/zorbo"] = (200, {"name": "Zorbo", "jobs": [{"shortcode": "x", "title": "T"}]})
    d = det.detect("Zorbo", transport=mock(routes))
    assert d.status == "found" and d.kind == "workable"


# ---------------------------------------------------------------- following companies

def test_follow_filters_titles_and_closes_by_full_board(client, monkeypatch):
    from app.db import session_scope
    from app.models import Job, JobSource
    from app.services.discovery import run_source

    h, _ = make_user(client)
    setup_profile(client, h)  # target title: Backend Engineer
    r = client.post("/api/companies/follow", headers=h, json={"run_now": False, "items": [
        {"kind": "greenhouse", "identifier": "Acme", "company": "Acme"}, {"kind": "greenhouse", "identifier": "acme"}]})
    assert r.json()["added"] == 1 and r.json()["already_following"] == 1
    sid = client.get("/api/companies", headers=h).json()[0]["id"]
    board = {"jobs": [{"id": 1, "title": "Senior Backend Engineer", "absolute_url": "u1"},
                      {"id": 2, "title": "Legal Counsel", "absolute_url": "u2"}]}
    t = mock({"https://boards-api.greenhouse.io/v1/boards/acme/jobs": (200, board),
              "https://boards-api.greenhouse.io/v1/boards/acme": (200, {"name": "Acme"})})
    with session_scope() as db:
        s = run_source(db, db.get(JobSource, sid), transport=t)
        assert s["on_board"] == 2 and s["matching"] == 1 and s["new"] == 1
    # the matching job is still on the board (even though the other changed) → stays active
    board["jobs"] = [{"id": 1, "title": "Senior Backend Engineer", "absolute_url": "u1"}]
    with session_scope() as db:
        s = run_source(db, db.get(JobSource, sid), transport=t)
        assert s["closed"] == 0
    board["jobs"] = []
    with session_scope() as db:
        assert run_source(db, db.get(JobSource, sid), transport=t)["closed"] == 1


def test_popular_list_and_new_connections(client):
    assert len(POPULAR) >= 100 and all(p["kind"] in ADAPTERS for p in POPULAR)
    assert len({(p["kind"], p["identifier"].lower()) for p in POPULAR}) == len(POPULAR)
    h, _ = make_user(client)
    pop = client.get("/api/companies/popular", headers=h).json()
    assert pop and not any(p["following"] for p in pop)
    client.post("/api/companies/follow", headers=h, json={"run_now": False, "items": [{"kind": pop[0]["kind"], "identifier": pop[0]["identifier"], "company": pop[0]["company"]}]})
    assert client.get("/api/companies/popular", headers=h).json()[0]["following"] is True
    assert client.put("/api/integrations/jsearch", headers=h, json={"rapidapi_key": "rk-secret-1234"}).json()["key_hint"] == "••••1234"
    assert client.put("/api/integrations/usajobs", headers=h, json={"usajobs_key": "k", "usajobs_email": "bad"}).status_code == 400
    assert client.put("/api/integrations/usajobs", headers=h, json={"usajobs_key": "k1", "usajobs_email": "me@example.com"}).json()["configured"]
    st = client.get("/api/discovery/auto", headers=h).json()
    js = next(s for s in st["sources"] if s["kind"] == "jsearch")
    assert js["key_ok"] and not next(s for s in st["sources"] if s["kind"] == "adzuna")["key_ok"]
