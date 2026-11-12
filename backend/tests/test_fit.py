"""Fit verdict: alerts and 'best fits' show roles the candidate fits, not every title sharing a keyword."""
from types import SimpleNamespace as NS

from app.services.matching import fit_verdict
from app.services.priority import alertable  # noqa: F401  (imported to make sure the module loads)

TARGETS = ["Software Engineer", "Backend Engineer"]


def job(title, years=None):
    jd = f"We need {years}+ years of experience building services." if years else "Build services in Python and Java."
    return NS(title=title, description_text=jd)


def v(title, years=None, score=72, title_score=1.0, yoe=3.0, prefs=None, targets=TARGETS, edu="meets", flags=()):
    return fit_verdict(job(title, years), prefs or {}, targets, yoe, score, title_score, edu, list(flags))


def test_roles_from_the_users_alert_email_are_not_good_fits():
    # the four roles that arrived in the alert email (ATS 39–44)
    assert v("Senior Software Engineer, Requirements , Amazon LEO, D2D Software", 5, score=44)["verdict"] == "poor"
    assert v("Senior Software Engineer - Embedded Networking, Payload Network Software Team", 5, score=44)["verdict"] == "poor"
    r = v("Senior Software Engineer Manager, YouTube Main App, Mobile", score=44)
    assert r["verdict"] == "poor" and any("people-manager" in x for x in r["reasons"])
    r = v("AI Software Business Development Manager", score=39, title_score=0.5)
    assert r["verdict"] == "poor" and any("business development" in x for x in r["reasons"])


def test_a_role_at_your_level_is_a_good_fit():
    r = v("Software Engineer II, Backend", 2, score=74)
    assert r["verdict"] == "good" and r["reasons"][0].startswith("Good fit") and "ATS 74" in r["reasons"][0]
    assert v("Software Engineer", 3, score=68)["verdict"] == "good"


def test_one_level_up_or_a_little_short_is_a_stretch():
    assert v("Senior Software Engineer", 4, score=78)["verdict"] == "stretch"
    assert v("Software Engineer", 5, score=78)["verdict"] == "stretch"  # 5 years asked, 3 held
    assert v("Software Engineer", 8, score=78)["verdict"] == "poor"     # far more years than held
    assert v("Software Engineer", score=58)["verdict"] == "stretch"


def test_preferences_and_targets_can_open_up_roles():
    # someone targeting management sees manager roles; seniority preferences raise the level
    assert v("Engineering Manager", score=75, targets=["Engineering Manager"])["verdict"] == "good"
    assert v("Senior Software Engineer", score=75, prefs={"seniority": ["senior"]})["verdict"] == "good"
    assert v("Product Manager, Payments", score=75, targets=["Product Manager"])["verdict"] == "good"


def test_blockers_make_it_a_poor_fit():
    assert v("Software Engineer", score=80, edu="below")["verdict"] == "poor"
    assert v("Software Engineer", score=80, flags=["Work authorization: posting says it cannot sponsor; your profile says you need sponsorship."])["verdict"] == "poor"
    assert v("Data Analyst", score=80, title_score=0.1)["verdict"] == "poor"


def test_alerts_only_send_good_fits(client):
    from app.db import SessionLocal
    from app.models import Job, MatchAssessment, User

    from .conftest import make_user

    _, email = make_user(client)
    with SessionLocal() as db:
        uid = db.query(User).filter_by(email=email).one().id
        ids = []
        for t, fit, sc in [("Software Engineer II", "good", 72), ("Senior Software Engineer", "stretch", 75),
                           ("Business Development Manager", "poor", 41)]:
            j = Job(user_id=uid, source_kind="mock", external_id=t, title=t, company="Acme", fingerprint=t, content_hash=t)
            db.add(j)
            db.flush()
            db.add(MatchAssessment(user_id=uid, job_id=j.id, score=sc, recommendation="review", breakdown={"_fit": {"reasons": []}},
                                   fit=fit, edu_status="meets"))
            ids.append(j.id)
        db.commit()
        assert [j.title for j, _ in alertable(db, uid, ids, 0)] == ["Software Engineer II"]
        assert {j.title for j, _ in alertable(db, uid, ids, 0, include_stretch=True)} == {"Software Engineer II", "Senior Software Engineer"}


def test_google_location_is_not_the_eeo_sentence():
    from app.services.sources.bigtech import _google_location

    assert _google_location("Equal opportunity: workplace discrimination is illegal , Belonging at Google , and How we hire .") == ""
    assert _google_location("corporate_fare Google place Sunnyvale, CA, USA") == "Sunnyvale, CA, USA"


def test_rescoring_keeps_one_assessment_per_job_and_dashboard_stays_light(client):
    from app.db import SessionLocal
    from app.models import MatchAssessment, User
    from app.services.insights import latest_scores
    from app.services.matching import score_job

    from .conftest import make_user, setup_profile
    from .test_api import _mock_jobs

    h, email = make_user(client)
    setup_profile(client, h)
    jobs = _mock_jobs(client, h)
    with SessionLocal() as db:
        uid = db.query(User).filter_by(email=email).one().id
        from app.models import Job
        j = db.get(Job, jobs[0]["id"])
        for _ in range(3):
            score_job(db, j)
        db.commit()
        assert db.query(MatchAssessment).filter_by(job_id=j.id).count() == 1
        sc = latest_scores(db, uid)
        assert set(sc) >= {x["id"] for x in jobs} and isinstance(sc[j.id].score, int)
        assert set(latest_scores(db, uid, [j.id])) == {j.id}
    assert client.get("/api/dashboard", headers=h).status_code == 200
