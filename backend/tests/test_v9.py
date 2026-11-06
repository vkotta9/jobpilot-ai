"""Fortune 500 company list: catalog shape, name detection, endpoint and following it all at once."""
import re

from app.services.sources import ADAPTERS, COMPANY_KINDS
from app.services.sources.catalog import FORTUNE_500, TOP_TECH


def test_fortune_500_has_every_rank_once_or_tied():
    assert len(FORTUNE_500) == 500
    ranks = [c["rank"] for c in FORTUNE_500]
    assert ranks == sorted(ranks) and ranks[0] == 1 and ranks[-1] == 500
    assert len(set(ranks)) >= 495  # Fortune lists a few ties (e.g. two companies at #160)
    assert len({c["company"] for c in FORTUNE_500}) == 500
    assert {c["category"] for c in FORTUNE_500} == {f"Ranks {a}–{a + 99}" for a in (1, 101, 201, 301, 401)}


def test_every_fortune_500_company_has_a_usable_source():
    for c in FORTUNE_500:
        assert c["kind"] in COMPANY_KINDS or c["kind"] == "jsearch", c
        assert c["kind"] in ADAPTERS, c
        assert c["via"] == ("google_jobs" if c["kind"] == "jsearch" else "direct")
        if c["kind"] == "workday":
            assert re.fullmatch(r"[a-z0-9-]+\|wd\d+\|[A-Za-z0-9_-]+", c["identifier"]), c
    direct = [c for c in FORTUNE_500 if c["via"] == "direct"]
    assert len(direct) >= 200


def test_fortune_500_reuses_verified_catalog_feeds():
    top = {c["company"]: c for c in TOP_TECH}
    f5 = {c["company"]: c for c in FORTUNE_500}
    assert (f5["Nvidia"]["kind"], f5["Nvidia"]["identifier"]) == (top["NVIDIA"]["kind"], top["NVIDIA"]["identifier"])
    assert f5["JPMorgan Chase"]["kind"] == "oraclehcm"
    assert f5["Ford Motor"]["kind"] == "oraclehcm" and f5["General Mills"]["kind"] == "workday"


def test_rejected_lookalike_feeds_stay_out():
    """Name-guessing found other organisations' boards; verification rejected them."""
    f5 = {c["company"]: c for c in FORTUNE_500}
    assert f5["Liberty Mutual Insurance"]["kind"] == "jsearch"  # 'liberty' Workday tenant is Liberty University
    assert f5["Owens Corning"]["kind"] == "jsearch"  # 'owens' is Owens Community College
    assert f5["Emerson Electric"]["kind"] == "jsearch"  # 'emerson' is Emerson College
    assert f5["Archer Daniels Midland"]["identifier"] == "ADM"


def test_google_jobs_names_match_employer_words():
    """JSearch keeps a posting only when every word of the identifier is in the employer name."""
    f5 = {c["company"]: c for c in FORTUNE_500}
    assert f5["Exxon Mobil"]["identifier"] == "ExxonMobil"
    assert f5["Valero Energy"]["identifier"] == "Valero"
    assert f5["Enterprise Products Partners"]["identifier"] == "Enterprise Products"
    for c in FORTUNE_500:
        if c["kind"] == "jsearch":
            assert 0 < len(c["identifier"]) <= 120 and not c["identifier"].startswith(" "), c


def test_every_fortune_500_company_can_be_followed():
    from app.api.companies import FollowItem

    for c in FORTUNE_500:
        FollowItem(kind=c["kind"], identifier=c["identifier"], company=c["company"])  # raises if rejected


def test_detect_finds_fortune_500_names_and_aliases():
    from app.services.sources.detect import _top_tech, detect

    idx = _top_tech()
    assert idx["kroger"]["company"] == "Kroger"
    assert idx["exxon"]["company"] == "Exxon Mobil"
    assert idx["nvidia"]["company"] == "NVIDIA"  # the top-tech entry wins over the Fortune 500 one
    d = detect("Kroger")
    assert d.kind == "jsearch" and d.identifier == "Kroger"


def test_fortune_500_endpoint_and_follow_everything(client):
    from .conftest import make_user

    h, _ = make_user(client)
    r = client.get("/api/companies/fortune-500", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["jsearch_connected"] is False and len(body["companies"]) == 500
    assert body["companies"][0]["company"] == "Amazon" and body["companies"][0]["rank"] == 1
    items = [{"kind": c["kind"], "identifier": c["identifier"], "company": c["company"]} for c in body["companies"]]
    r = client.post("/api/companies/follow", headers=h, json={"run_now": False, "items": items})
    assert r.status_code == 200, r.text
    assert r.json()["added"] >= 495  # a few Fortune names share one feed (e.g. the same catalog entry)
    after = client.get("/api/companies/fortune-500", headers=h).json()["companies"]
    assert all(c["following"] for c in after)
