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


def _full_skills_pdf() -> bytes:
    import io

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = letter[1] - 50

    def text(x, s, font="Times-Roman", size=10):
        c.setFont(font, size)
        c.drawString(x, y, s)

    text(240, "Sam Lee", "Times-Bold", 17); y -= 22
    text(43, "Summary", "Times-Bold", 14); y -= 16
    text(43, "Software engineer with 4 years building backend services in Python for fintech teams.")
    y -= 12
    text(43, "Focused on reliable APIs.")
    y -= 20
    text(43, "Experience", "Times-Bold", 14); y -= 16
    for b in ["Built payment APIs in Python with Docker and Terraform on AWS, cutting latency by 20%.",
              "Set up Jenkins pipelines and Grafana dashboards for 12 services."]:
        text(43, "•"); text(52, b); y -= 13
    y -= 8
    text(43, "Technical Skills", "Times-Bold", 14); y -= 16
    for label, items in [("Languages:", "Python, SQL, MATLAB, Visual Basic, Fortran, COBOL, Pascal, Perl, Haskell, Lisp, Prolog, Ada"),
                         ("Tools:", "Git, Photoshop, Excel, Tableau, Illustrator, Premiere Pro, InDesign, Lightroom, Figma, SPSS, AutoCAD")]:
        c.setFont("Times-Bold", 10); c.drawString(43, y, label)
        w = c.stringWidth(label, "Times-Bold", 10)
        c.setFont("Times-Roman", 10); c.drawString(43 + w + 3, y, items); y -= 12
    c.save()
    return buf.getvalue()


def test_full_skills_line_makes_room_and_uses_summary(monkeypatch):
    from app.services import inplace_pdf, llm, tailor_inplace

    from .test_v2 import _NoDB

    pdf = _full_skills_pdf()

    class J:
        id, title, company = 1, "Backend Engineer", "Acme"
        description_text = ("Requirements\n- Python, SQL, Docker, Terraform, Jenkins, Grafana and AWS\n- REST APIs and Kubernetes\n"
                            "- Bachelor's degree in Computer Science")

    class R:
        id, user_id, mime_type, original_filename, storage_name = 1, 1, "pdf", "r.pdf", "x"
        file_data = pdf

    monkeypatch.setattr(llm, "config_for", lambda db, uid: None)
    content, flags, gen = tailor_inplace.build_plan(_NoDB(), 1, J(), R())
    sk = {s["display"].lower(): s for s in content["skills"]}
    assert {"docker", "terraform", "jenkins", "grafana"} <= set(sk)  # evidenced in bullets
    removed = {r["display"] for r in content["skill_removals"]}
    assert removed and not ({"Python", "SQL", "Git"} & removed)  # only skills the job doesn't mention are dropped
    placed_skills = [s for s in content["skills"] if s["selected"] and s["placed"] == "skills"]
    assert placed_skills
    out, warnings = tailor_inplace.render(content, R())
    text = inplace_pdf.full_text(out)
    for s in placed_skills:
        assert s["display"] in text
    assert "Python, SQL" in text and "Sam Lee" in text
    for s in content["skills"]:
        if s.get("placed") == "summary":
            assert s["display"] in text  # moved into the summary


def test_approval_works_with_master_resume_without_tailoring(client):
    from .conftest import sample_docx_bytes
    from .test_api import _mock_jobs

    h, _ = make_user(client)
    setup_profile(client, h)
    up = client.post("/api/resumes", headers=h, files={"file": ("cv.docx", sample_docx_bytes(), "application/octet-stream")}).json()
    job = _mock_jobs(client, h)[0]
    app_id = client.post(f"/api/jobs/{job['id']}/shortlist", headers=h).json()["application_id"]
    r = client.post(f"/api/applications/{app_id}/request-approval", headers=h).json()
    assert r["ok"] is True, r  # no tailored resume needed
    det = client.get(f"/api/applications/{app_id}", headers=h).json()
    assert det["resume_used"] == {"type": "master", "resume_id": up["resume"]["id"], "filename": "cv.docx"}
    assert client.post(f"/api/applications/{app_id}/approve", json={"confirm": True}, headers=h).status_code == 200
    # a tailored draft doesn't block; once approved it's used instead
    rd = client.post(f"/api/jobs/{job['id']}/resume/tailor", headers=h).json()
    assert client.get(f"/api/applications/{app_id}", headers=h).json()["approval_current"] is False
    assert client.post(f"/api/applications/{app_id}/request-approval", headers=h).json()["ok"] is True
    client.post(f"/api/documents/{rd['id']}/approve", json={"confirm": True}, headers=h)
    assert client.get(f"/api/applications/{app_id}", headers=h).json()["resume_used"]["type"] == "tailored"


def test_approval_needs_some_resume(client):
    from .test_api import _mock_jobs

    h, _ = make_user(client)
    setup_profile(client, h)
    job = _mock_jobs(client, h)[0]
    app_id = client.post(f"/api/jobs/{job['id']}/shortlist", headers=h).json()["application_id"]
    r = client.post(f"/api/applications/{app_id}/request-approval", headers=h).json()
    assert r["ok"] is False and any("Resume library" in p for p in r["problems"])


def test_triage_tabs_skip_later_apply_restore_delete(client):
    from .test_api import _mock_jobs

    h, _ = make_user(client)
    setup_profile(client, h)
    jobs = _mock_jobs(client, h)
    ids = [j["id"] for j in jobs]
    r = client.get("/api/jobs?view=new", headers=h).json()
    assert r["counts"] == {"new": 5, "later": 0, "applied": 0, "skipped": 0} and r["total"] == 5
    assert client.post(f"/api/jobs/{ids[0]}/triage", headers=h, json={"action": "skip"}).json()["triage"] == "skipped"
    client.post(f"/api/jobs/{ids[1]}/triage", headers=h, json={"action": "later"})
    client.post(f"/api/jobs/{ids[2]}/shortlist", headers=h)  # Apply →
    r = client.get("/api/jobs?view=new", headers=h).json()
    assert r["counts"] == {"new": 2, "later": 1, "applied": 1, "skipped": 1}
    assert {j["id"] for j in client.get("/api/jobs?view=skipped", headers=h).json()["items"]} == {ids[0]}
    assert {j["id"] for j in client.get("/api/jobs?view=later", headers=h).json()["items"]} == {ids[1]}
    assert {j["id"] for j in client.get("/api/jobs?view=applied", headers=h).json()["items"]} == {ids[2]}
    # filters apply inside every tab
    assert client.get("/api/jobs?view=skipped&min_score=101", headers=h).json()["total"] == 0
    # restore, bulk, delete
    client.post(f"/api/jobs/{ids[0]}/triage", headers=h, json={"action": "restore"})
    assert client.post("/api/jobs/triage-bulk", headers=h, json={"ids": [ids[3], ids[4]], "action": "skip"}).json()["changed"] == 2
    client.post("/api/jobs/triage-bulk", headers=h, json={"ids": [ids[3]], "action": "delete"})
    r = client.get("/api/jobs?view=new", headers=h).json()
    assert r["counts"] == {"new": 1, "later": 1, "applied": 1, "skipped": 1}
    assert ids[3] not in {j["id"] for j in client.get("/api/jobs?view=all", headers=h).json()["items"]}
    # changing your mind before applying: Skip an application in progress
    client.post(f"/api/jobs/{ids[2]}/triage", headers=h, json={"action": "skip"})
    assert client.get("/api/jobs?view=new", headers=h).json()["counts"]["applied"] == 0
    # a rediscovered skipped job stays skipped (decision kept)
    s = client.get("/api/sources", headers=h).json()[0]
    client.post(f"/api/sources/{s['id']}/run", headers=h)
    assert client.get("/api/jobs?view=new", headers=h).json()["counts"]["skipped"] == 2
