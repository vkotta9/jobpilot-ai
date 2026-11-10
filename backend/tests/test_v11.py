"""ATS score measures candidates against the preferred qualifications, not just the minimum."""
from app.services import ats

JD = """Senior Software Engineer
Required Qualifications:
Bachelor's Degree in Computer Science or related technical field AND 4+ years technical engineering experience with coding in languages including, but not limited to, C, C++, C#, Java, JavaScript, TypeScript, or Python
OR equivalent experience.
Preferred Qualifications:
Master's Degree in Computer Science or related technical field AND 6+ years technical engineering experience with coding in languages including, but not limited to, C, C++, C#, Java, JavaScript, TypeScript, or Python
OR Bachelor's Degree in Computer Science or related technical field AND 8+ years technical engineering experience with coding in languages including, but not limited to, C, C++, C#, Java, JavaScript, TypeScript, or Python
Experience building production systems with large language models, such as AI agents, multi-agent orchestration, tool calling, planning, context management, or code-understanding systems.
Experience building or working on security scanners, static analysis (SAST), dynamic analysis (DAST), software composition analysis (SCA), compilers, or other program analysis tools.
Working knowledge of vulnerability classes such as memory safety, injection, authentication and authorization, deserialization, path traversal, SSRF, and business-logic flaws.
Experience with program analysis techniques such as taint analysis, data-flow and control-flow analysis, code property graphs, fuzzing, or symbolic execution.
Benefits
Great benefits.
"""


def _cv(years_from: int, degree: str, skills: str) -> str:
    return (f"Alex Kim\nSoftware Engineer | Contoso | Jan {years_from} - Present\nBuilt services in Java and Python.\n"
            f"Education\n{degree} Computer Science\nSkills\n{skills}")


def test_list_items_reads_preferred_bullets():
    items, mode = ats.list_items("Experience with program analysis techniques such as taint analysis, data-flow and "
                                 "control-flow analysis, code property graphs, fuzzing, or symbolic execution.")
    assert mode == "any" and {"taint analysis", "fuzzing", "symbolic execution", "code property graphs"} <= set(items)
    items, mode = ats.list_items("Working knowledge of vulnerability classes such as memory safety, injection, "
                                 "authentication and authorization, deserialization, path traversal, SSRF, and business-logic flaws.")
    assert mode == "all" and {"ssrf", "authentication", "authorization", "path traversal"} <= set(items)
    items, _ = ats.list_items("Experience building or working on security scanners, static analysis (SAST), dynamic "
                              "analysis (DAST), software composition analysis (SCA), compilers, or other program analysis tools.")
    assert {"sast", "dast", "sca", "static analysis", "security scanners", "compilers"} <= set(items)
    assert not any("other" in i or "tools" in i for i in items)
    assert ats.list_items("Strong communication skills.") == ([], "")


def test_any_of_language_list_counts_once():
    kws = {k.term: k for k in ats.extract_keywords(JD)}
    assert kws["java"].group and kws["java"].group == kws["python"].group == kws["typescript"].group
    r = ats.score(_cv(2016, "B.S.", "Java"), "Senior Software Engineer", JD)
    assert "python" not in r["missing_required"] and "c++" not in r["missing"]  # Java alone meets the list


def test_preferred_years_follow_the_candidates_degree():
    bars = ats.experience_bars(JD, have_degree=1)
    assert bars["required"]["years"] == 4 and bars["preferred"]["years"] == 8
    assert ats.experience_bars(JD, have_degree=2)["preferred"]["years"] == 6
    s_min, note = ats.experience_score(5, ats.experience_bars(JD, 1))
    s_pref, _ = ats.experience_score(9, ats.experience_bars(JD, 1))
    s_low, _ = ats.experience_score(2, ats.experience_bars(JD, 1))
    assert s_low < 0.75 <= s_min < s_pref == 1.0
    assert "3 short of the preferred" in note


def test_preferred_qualifications_raise_the_score():
    base = _cv(2020, "B.S.", "Java, Python")
    strong = _cv(2016, "M.S.", "Java, Python, AI agents, tool calling, static analysis, SAST, taint analysis, fuzzing, "
                               "injection, SSRF, memory safety, deserialization")
    a, b = ats.score(base, "Senior Software Engineer", JD), ats.score(strong, "Senior Software Engineer", JD)
    assert b["score"] >= a["score"] + 20
    assert a["preferred"]["skills_found"] == 0 and a["preferred"]["skills_total"] == 4
    assert b["preferred"]["skills_found"] == 4 and b["preferred"]["meets_years"] is True
    assert a["preferred"]["meets_years"] is False and a["preferred"]["years"] == 8


def test_higher_preferred_degree_without_an_open_path_is_a_gap():
    jd = "Requirements:\nBachelor's degree in Computer Science.\nPreferred:\nMaster's degree preferred.\n"
    r = ats.score(_cv(2018, "B.S.", "Python"), "Software Engineer", jd)
    assert r["breakdown"]["education"]["score"] == 0.8 and "master's is preferred" in r["breakdown"]["education"]["note"]
    assert r["preferred"]["meets_degree"] is False
    r2 = ats.score(_cv(2018, "M.S.", "Python"), "Software Engineer", jd)
    assert r2["breakdown"]["education"]["score"] == 1.0


def test_example_lists_give_partial_credit():
    one = ats.score(_cv(2016, "M.S.", "Java, injection"), "Senior Software Engineer", JD)
    half = ats.score(_cv(2016, "M.S.", "Java, injection, SSRF, memory safety, deserialization"), "Senior Software Engineer", JD)
    assert half["breakdown"]["keywords"]["score"] > one["breakdown"]["keywords"]["score"]


def test_explanation_mentions_preferred_bar(client):
    from .conftest import make_user, setup_profile

    h, _ = make_user(client)
    setup_profile(client, h)
    j = client.post("/api/jobs/manual", headers=h, json={"title": "Senior Software Engineer", "company": "Contoso",
                                                         "description_text": JD}).json()["job"]
    d = client.get(f"/api/jobs/{j['id']}", headers=h).json()
    assert "preferred qualifications" in d["match"]["explanation"]
    assert d["match"]["breakdown"]["_preferred"]["skills_total"] == 4


def test_old_scores_are_rescored_in_the_background(client):
    from app.db import SessionLocal
    from app.models import MatchAssessment, User
    from app.services.discovery import score_unscored
    from app.services.matching import SCORING_VERSION

    from .conftest import make_user, setup_profile

    h, email = make_user(client)
    setup_profile(client, h)
    jid = client.post("/api/jobs/manual", headers=h, json={"title": "Senior Software Engineer", "company": "Contoso",
                                                           "description_text": JD}).json()["job"]["id"]
    with SessionLocal() as db:
        uid = db.query(User).filter_by(email=email).one().id
        db.query(MatchAssessment).filter_by(job_id=jid).update({"scoring_version": 1})  # scored by the old model
        db.commit()
        assert score_unscored(db, uid) == 1
        newest = db.query(MatchAssessment).filter_by(job_id=jid).order_by(MatchAssessment.id.desc()).first()
        assert newest.scoring_version == SCORING_VERSION
        assert score_unscored(db, uid) == 0
