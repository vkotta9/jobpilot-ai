"""Degree fit, job filters (score range, posted within, sorting) and ATS weight presets."""
from datetime import timedelta

from app.services import ats
from app.services.matching import WEIGHT_PRESETS, auto_preset, effective_weights, resolve_preset

from .conftest import make_user, setup_profile


def test_degree_requirement_parsing():
    r = ats.degree_requirement("Minimum qualifications:\nBachelor's degree in Computer Science or related technical field, "
                               "or equivalent practical experience.\nPreferred qualifications:\nMaster's degree or PhD in Computer Science.")
    assert r["required"] == 1 and r["preferred"] == 3 and r["equivalent_ok"]
    assert ats.degree_requirement("Requirements\n- PhD in Machine Learning or a related field")["required"] == 3
    assert ats.degree_requirement("What you need: BS/MS in Computer Science. Master's preferred.")["required"] == 1
    assert ats.degree_requirement("Requirements: Master's degree in Computer Science required; PhD a plus.")["required"] == 2
    assert ats.degree_requirement("We use MS Office; p99 latency under 10 ms.")["required"] == 0
    assert ats.degree_levels("Microsoft Office, MS Excel, 5 ms") == set()


def test_education_match_rules():
    ms = ["Master of Science Computer Science"]
    assert ats.education_match("Requirements\nBachelor's degree in Computer Science", "", ms)["status"] == "exceeds"
    assert ats.education_match("Requirements\nMaster's degree in Computer Science", "", ms)["status"] == "meets"
    phd = ats.education_match("Requirements\nPhD in Computer Science", "", ms)
    assert phd["status"] == "below" and phd["score"] < 0.2
    assert ats.education_match("Requirements\nPhD in Computer Science", "", ["B.S. Computer Science"])["status"] == "below"
    assert ats.education_match("Requirements\nBS, MS or PhD in Computer Science", "", ["B.S. Computer Science"])["status"] == "meets"
    # resume text only: education section wins over mentions elsewhere
    cv = "EDUCATION\nB.S. Computer Science, State University\nEXPERIENCE\nWorked with PhD researchers"
    assert ats.education_match("Requirements\nMaster's in Computer Science", cv)["have"] == 1
    assert ats.education_match("Great team, fast pace.", cv)["status"] == "none"


def test_weight_presets_and_auto():
    assert resolve_preset({}) == "auto"
    assert resolve_preset(dict(WEIGHT_PRESETS["typical"])) == "auto"  # saved defaults from before presets
    assert resolve_preset({**WEIGHT_PRESETS["typical"], "keywords": 70}) == "custom"
    assert resolve_preset({"preset": "research"}) == "research"
    assert auto_preset("") == "entry"
    assert auto_preset("Engineer, Acme  Jan 2015 – Present") == "experienced"
    assert effective_weights({"preset": "entry"}) == WEIGHT_PRESETS["entry"]
    assert effective_weights({"preset": "custom", "keywords": 70, "title": 10, "experience": 10, "education": 5, "soft_skills": 5})["keywords"] == 70


def test_job_filters_and_degree_hiding(client):
    from app.db import session_scope
    from app.models import Job, utcnow

    h, _ = make_user(client)
    setup_profile(client, h, education=[{"institution": "State U", "degree": "Master of Science", "field": "Computer Science"}])
    uid = client.get("/api/auth/me", headers=h).json()["id"]
    body = "Requirements\n- 3+ years of Python, FastAPI, PostgreSQL, Docker and AWS experience building backend services.\n"
    now = utcnow()
    with session_scope() as db:
        rows = [
            ("Backend Engineer", body + "- Bachelor's degree in Computer Science", now - timedelta(hours=5)),
            ("Research Scientist", body + "- PhD in Computer Science required", now - timedelta(hours=10)),
            ("Python Developer", body + "- Master's degree in Computer Science", now - timedelta(days=5)),
            ("Office Manager", "Requirements\n- Scheduling, payroll and vendor management experience.", now - timedelta(days=20)),
        ]
        for i, (t, d, posted) in enumerate(rows):
            db.add(Job(user_id=uid, source_kind="manual", external_id=f"f{i}", fingerprint=f"fp{uid}{i}", title=t, company="Acme",
                       description_text=d * 3, posted_at=posted, discovered_at=posted))
        db.commit()
    from app.services.matching import score_jobs

    with session_scope() as db:
        score_jobs(db, uid)
    r = client.get("/api/jobs", headers=h).json()
    titles = [j["title"] for j in r["items"]]
    assert "Research Scientist" not in titles and r["hidden_higher_degree"] == 1  # PhD-only role hidden for an MS
    edu = {j["title"]: j["match"]["edu_status"] for j in r["items"]}
    assert edu["Backend Engineer"] == "exceeds" and edu["Python Developer"] == "meets"
    allr = client.get("/api/jobs?qualified_only=false", headers=h).json()
    assert "Research Scientist" in [j["title"] for j in allr["items"]]
    assert next(j for j in allr["items"] if j["title"] == "Research Scientist")["match"]["recommendation"] == "skip"
    # posted within 24h / 1 week
    assert {j["title"] for j in client.get("/api/jobs?posted_within=24", headers=h).json()["items"]} == {"Backend Engineer"}
    assert len(client.get("/api/jobs?posted_within=168", headers=h).json()["items"]) == 2
    # score range + sorting
    scores = sorted(j["match"]["score"] for j in r["items"])
    lo, hi = scores[0], scores[-1]
    ranged = client.get(f"/api/jobs?min_score={lo + 1}&max_score={hi}", headers=h).json()["items"]
    assert all(lo < j["match"]["score"] <= hi for j in ranged)
    newest = client.get("/api/jobs?sort=posted", headers=h).json()["items"]
    assert newest[0]["title"] == "Backend Engineer" and newest[-1]["title"] == "Office Manager"
    asc = [j["match"]["score"] for j in client.get("/api/jobs?sort=score_asc", headers=h).json()["items"]]
    assert asc == sorted(asc)
    # profile exposes the weight presets
    aw = client.get("/api/profile", headers=h).json()["ats_weights"]
    assert aw["preset"] == "auto" and set(aw["presets"]) == {"typical", "entry", "experienced", "research"}
    client.patch("/api/profile", headers=h, json={"match_weights": {"preset": "research"}})
    assert client.get("/api/profile", headers=h).json()["ats_weights"]["effective"] == WEIGHT_PRESETS["research"]


def test_country_inference():
    from app.services.geo import countries_of, in_country

    us = ["Austin, Texas, United States of America", "Seattle, WA, USA", "New York, NY", "Remote — US", "San Francisco",
          "US-CA-Mountain View", "Sunnyvale, CA", "Atlanta, Georgia"]
    assert all("US" in countries_of(l) for l in us)
    assert countries_of("Bengaluru, Karnataka, India") == {"IN"} and countries_of("Toronto, ON, Canada") == {"CA"}
    assert countries_of("London, UK; Remote") == {"GB"} and countries_of("Paris, France; New York, NY") == {"FR", "US"}
    assert in_country("Remote — Anywhere", "remote", "US") and not in_country("Berlin", "onsite", "US")
    assert in_country("2 Locations", "onsite", "US", url="https://gm.wd5.myworkdayjobs.com/Careers_GM/job/Austin-Texas-United-States-of-America/Engineer_JR1")


def test_country_filter_api(client):
    from app.db import session_scope
    from app.models import Job

    h, _ = make_user(client)
    uid = client.get("/api/auth/me", headers=h).json()["id"]
    with session_scope() as db:
        for i, loc in enumerate(["Seattle, WA, USA", "Bengaluru, India", "Remote — Anywhere", "London, UK"]):
            db.add(Job(user_id=uid, source_kind="manual", external_id=f"c{i}", fingerprint=f"cf{uid}{i}", title=f"Engineer {i}",
                       company="Acme", location=loc, remote_type="remote" if "Remote" in loc else "onsite", description_text="x"))
        db.commit()
    us = {j["location"] for j in client.get("/api/jobs?country=US", headers=h).json()["items"]}
    assert us == {"Seattle, WA, USA", "Remote — Anywhere"}
    assert {j["location"] for j in client.get("/api/jobs?country=IN", headers=h).json()["items"]} == {"Bengaluru, India", "Remote — Anywhere"}
    assert len(client.get("/api/jobs", headers=h).json()["items"]) == 4
