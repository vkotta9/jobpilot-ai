"""Startups: the verified startup list and the Hacker News "Who is hiring?" source."""
import httpx

from app.services.sources import ADAPTERS, FREE_DEFAULT_KINDS, KEYWORD_KINDS
from app.services.sources.catalog import STARTUPS
from app.services.sources.hn import HNHiringAdapter, parse_post

from .conftest import make_user, setup_profile


def test_startups_list_is_verified_direct_feeds():
    assert len(STARTUPS) >= 200
    assert all(c["via"] == "direct" and c["kind"] in ADAPTERS for c in STARTUPS)
    names = {c["company"] for c in STARTUPS}
    assert {"Cognition", "Sierra", "Ramp", "Anduril", "Wiz"} & names
    assert not {"Neon", "Sila", "Palmetto", "Otter.ai"} & names  # lookalike boards rejected during verification
    cats = {c["category"] for c in STARTUPS}
    assert {"AI & ML", "Fintech & crypto", "Security", "Health"} <= cats


def test_parse_hiring_posts():
    p = parse_post('Acme AI (YC W24) | Senior Backend Engineer, ML Engineer | San Francisco or REMOTE (US) | $160k-$210k | '
                   '<a href="https:&#x2F;&#x2F;acme.ai&#x2F;careers">acme.ai/careers</a><p>We build agents.')
    assert p["company"] == "Acme AI" and p["roles"] == ["Senior Backend Engineer", "ML Engineer"]
    assert p["remote"] and p["url"] == "https://acme.ai/careers" and "San Francisco" in p["location"]
    p = parse_post("3ive | Staff Software Engineer | REMOTE (Europe) | Python, TypeScript, React, AI Agents | https://x.io")
    assert p["location"] == "REMOTE (Europe)"  # a tech-stack segment isn't a location
    p = parse_post("Coder | https://coder.com/<p>[1]Senior Customer Support Engineer • North America • Full time<p>[2]Staff Software Engineer • Remote")
    assert "Staff Software Engineer" in p["roles"]
    assert parse_post("Are you sponsoring visas?") is None


def _transport():
    story = {"hits": [{"objectID": "900", "title": "Ask HN: Who wants to be hired? (November 2026)"},
                      {"objectID": "901", "title": "Ask HN: Who is hiring? (November 2026)"}]}
    comments = {"hits": [
        {"objectID": "1", "parent_id": 901, "created_at": "2026-11-02T15:00:00Z",
         "comment_text": "Coder | https://coder.com/<p>[1]Senior Customer Support Engineer • North America<p>[2]Staff Software Engineer • Remote"},
        {"objectID": "2", "parent_id": 901, "created_at": "2026-11-02T16:00:00Z",
         "comment_text": "Bakery Co | Head Baker | Austin, TX | ONSITE"},
        {"objectID": "3", "parent_id": 1, "created_at": "2026-11-02T17:00:00Z",  # a reply, not a post
         "comment_text": "Acme | Software Engineer | Remote"},
        {"objectID": "4", "parent_id": 901, "created_at": "2026-11-03T10:00:00Z",
         "comment_text": 'Northwind | Founding Machine Learning Engineer | New York, NY | ONSITE | <a href="https://northwind.dev/jobs">jobs</a>'},
    ]}

    def handler(req: httpx.Request):
        if req.url.path.endswith("/search_by_date"):
            return httpx.Response(200, json=story)
        assert req.url.params["tags"] == "comment,story_901"
        return httpx.Response(200, json=comments)
    return httpx.MockTransport(handler)


def test_hn_adapter_keeps_matching_posts_from_this_months_thread():
    a = HNHiringAdapter("auto", transport=_transport(), sleep=lambda s: None,
                        context={"queries": ["Software Engineer"], "title_terms": ["Software Engineer", "Machine Learning Engineer"]})
    jobs = {j.company: j for j in a.fetch()}
    assert set(jobs) == {"Coder", "Northwind"}  # the baker and the reply are skipped
    assert jobs["Coder"].title == "Staff Software Engineer"  # best-matching role, not the first
    assert jobs["Coder"].url == "https://news.ycombinator.com/item?id=1"
    assert jobs["Northwind"].apply_url == "https://northwind.dev/jobs" and jobs["Northwind"].remote_type == "onsite"
    assert "Who is hiring? (November 2026)" in jobs["Northwind"].description_text


def test_hn_source_is_on_by_default_in_find_jobs_for_me(client):
    assert "hn_hiring" in KEYWORD_KINDS and "hn_hiring" in FREE_DEFAULT_KINDS
    h, _ = make_user(client)
    setup_profile(client, h)
    st = client.get("/api/discovery/auto", headers=h).json()
    hn = next(s for s in st["sources"] if s["kind"] == "hn_hiring")
    assert hn["default_on"] and not hn["needs_key"] and "Hacker News" in hn["label"]


def test_startups_endpoint_and_name_detection(client):
    from app.services.sources.detect import _top_tech

    h, _ = make_user(client)
    r = client.get("/api/companies/startups", headers=h).json()
    assert len(r["companies"]) == len(STARTUPS) and all(not c["following"] for c in r["companies"])
    assert _top_tech()["cognition"]["kind"] == "ashby" and _top_tech()["cognition"]["identifier"] == "cognition"
    items = [{"kind": c["kind"], "identifier": c["identifier"], "company": c["company"]} for c in r["companies"][:20]]
    out = client.post("/api/companies/follow", headers=h, json={"run_now": False, "items": items}).json()
    assert out["added"] == 20
