"""End-to-end API tests: full workflow, approval gates, authorization, privacy."""
import csv
import io

from app.config import settings
from app.db import session_scope
from app.models import JobSource, UserSettings
from app.services.discovery import run_source
from app.services.sources.base import NormalizedJob

from .conftest import make_user, sample_docx_bytes, setup_profile
from .test_units import GH_PAYLOAD, LEVER_PAYLOAD, transport_for


def _mock_jobs(client, h):
    s = client.post("/api/sources", json={"kind": "mock", "identifier": "acme"}, headers=h).json()
    r = client.post(f"/api/sources/{s['id']}/run", headers=h).json()
    assert r["new"] == 5 and r["simulated"] is True
    return client.get("/api/jobs?sort=score", headers=h).json()["items"]


def test_full_workflow(client):
    h, _ = make_user(client)
    setup_profile(client, h)
    # resume upload & parse
    cv = sample_docx_bytes()
    up = client.post("/api/resumes", headers=h, files={"file": ("cv.docx", cv, "application/octet-stream")})
    assert up.status_code == 200, up.text
    assert up.json()["resume"]["parsed"]["experience"]
    dup = client.post("/api/resumes", headers=h, files={"file": ("cv2.docx", cv, "application/octet-stream")})
    assert dup.json()["duplicate"] is True
    # fill-empty never overwrites the confirmed profile
    res = client.post(f"/api/resumes/{up.json()['resume']['id']}/apply-to-profile", headers=h).json()
    assert "full_name" not in res["updated_fields"] and "experience" not in res["updated_fields"]

    jobs = _mock_jobs(client, h)
    assert all(j["is_simulated"] for j in jobs)
    assert all(j["match"] is not None for j in jobs)
    backend = next(j for j in jobs if j["title"] == "Senior Backend Engineer")
    detail = client.get(f"/api/jobs/{backend['id']}", headers=h).json()
    assert any("SIMULATED" in f for f in detail["match"]["flags"])

    # tailor + letter
    rd = client.post(f"/api/jobs/{backend['id']}/resume/tailor", headers=h).json()
    # an uploaded resume is tailored in place: same file format, header untouched
    assert rd["content"]["format"] == "inplace" and rd["content"]["file_kind"] == "docx"
    assert "ats_before" in rd["content"] and "ats_after" in rd["content"]
    ld = client.post(f"/api/jobs/{backend['id']}/cover-letter", headers=h).json()
    app_id = client.post(f"/api/jobs/{backend['id']}/shortlist", headers=h).json()["application_id"]

    # gate 1: can't jump to applied or record submission
    assert client.post(f"/api/applications/{app_id}/status", json={"status": "applied"}, headers=h).status_code == 400
    assert client.post(f"/api/applications/{app_id}/submission", json={"confirm": True}, headers=h).status_code == 400
    # gate 2: approval refused while documents unapproved
    r = client.post(f"/api/applications/{app_id}/request-approval", headers=h).json()
    assert r["ok"] is False and r["problems"]
    assert client.post(f"/api/applications/{app_id}/approve", json={"confirm": True}, headers=h).status_code == 400

    # cover letter placeholder blocks approval until filled
    assert client.post(f"/api/documents/{ld['id']}/approve", json={"confirm": True}, headers=h).status_code == 400
    body = ld["content"]["body"].split("[[ADD:")[0] + "I admire the team's API work.\n\nSincerely,\nJordan Rivera"
    assert client.put(f"/api/documents/{ld['id']}", json={"content": {"body": body}}, headers=h).status_code == 200
    assert client.post(f"/api/documents/{ld['id']}/approve", json={"confirm": True}, headers=h).status_code == 200
    assert client.post(f"/api/documents/{rd['id']}/approve", json={"confirm": False}, headers=h).status_code == 400
    assert client.post(f"/api/documents/{rd['id']}/approve", json={"confirm": True}, headers=h).status_code == 200

    # screening questions: personal ones need input
    qs = client.post(f"/api/applications/{app_id}/questions", headers=h,
                     json={"questions": ["Will you now or in the future require sponsorship?", "What are your salary expectations?",
                                         "Are you legally authorized to work in the US?", "Tell us about your relevant experience"]}).json()
    by_cat = {q["category"]: q for q in qs}
    assert by_cat["sponsorship"]["status"] == "needs_input"  # profile left it unset — never guessed
    assert by_cat["salary"]["status"] == "needs_input" and by_cat["salary"]["answer"] == ""
    assert by_cat["work_authorization"]["status"] == "draft" and "United States" in by_cat["work_authorization"]["answer"]
    assert by_cat["general"]["answer"]
    assert client.put(f"/api/answers/{by_cat['salary']['id']}", json={"answer": "", "approve": True}, headers=h).status_code == 400
    for q, ans in [(by_cat["sponsorship"], "No"), (by_cat["salary"], "Open to discussing"), (by_cat["work_authorization"], None), (by_cat["general"], None)]:
        r = client.put(f"/api/answers/{q['id']}", json={"answer": ans or q["answer"], "approve": True, "reusable": q is by_cat["sponsorship"]}, headers=h)
        assert r.status_code == 200

    # approval flow
    r = client.post(f"/api/applications/{app_id}/request-approval", headers=h).json()
    assert r["ok"] is True, r
    assert client.post(f"/api/applications/{app_id}/approve", json={"confirm": False}, headers=h).status_code == 400
    assert client.post(f"/api/applications/{app_id}/approve", json={"confirm": True}, headers=h).status_code == 200

    # editing after approval invalidates it
    doc = client.get(f"/api/documents/{rd['id']}", headers=h).json()
    bullet = next(u for u in doc["content"]["units"] if u["kind"] == "bullet")
    bullet["final"], bullet["accepted"] = "Delivered the payments API in **Python** and FastAPI", True
    assert client.put(f"/api/documents/{rd['id']}", json={"content": doc["content"]}, headers=h).status_code == 200
    det = client.get(f"/api/applications/{app_id}", headers=h).json()
    assert det["approval_current"] is False and det["status"] == "preparing"
    assert client.post(f"/api/applications/{app_id}/submission", json={"confirm": True}, headers=h).status_code == 400

    # re-approve and record submission
    client.post(f"/api/documents/{rd['id']}/approve", json={"confirm": True}, headers=h)
    assert client.post(f"/api/applications/{app_id}/request-approval", headers=h).json()["ok"]
    client.post(f"/api/applications/{app_id}/approve", json={"confirm": True}, headers=h)
    r = client.post(f"/api/applications/{app_id}/submission", headers=h,
                    json={"confirm": True, "confirmation_detail": "Confirmation #GH-88812 received by email"}).json()
    assert r["verified"] is True
    assert client.post(f"/api/applications/{app_id}/submission", json={"confirm": True}, headers=h).status_code == 409

    det = client.get(f"/api/applications/{app_id}", headers=h).json()
    assert det["status"] == "applied" and det["tasks"], "follow-up task should be auto-created"
    assert any(e["kind"] == "submitted" and e["verified"] for e in det["events"])

    # tracker updates
    assert client.post(f"/api/applications/{app_id}/status", json={"status": "interview"}, headers=h).status_code == 200
    assert client.patch(f"/api/applications/{app_id}", json={"follow_up_at": "2026-11-02", "notes": "Recruiter call"}, headers=h).status_code == 200

    # downloads are real files
    assert client.get(f"/api/documents/{rd['id']}/download?format=pdf", headers=h).status_code == 400  # keeps DOCX
    tailored = client.get(f"/api/documents/{rd['id']}/download?format=docx", headers=h)
    assert tailored.status_code == 200 and tailored.content[:2] == b"PK"
    import docx as _docx
    paras = [p.text for p in _docx.Document(io.BytesIO(tailored.content)).paragraphs]
    assert "Delivered the payments API in Python and FastAPI" in paras
    assert "jordan@example.com | +1 555 010 2030 | github.com/jordan" in paras  # contact line untouched
    pdf = client.get(f"/api/documents/{ld['id']}/download?format=pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    docx = client.get(f"/api/documents/{ld['id']}/download?format=docx", headers=h)
    assert docx.content[:2] == b"PK"

    # CSV export
    csv_text = client.get("/api/applications/export.csv", headers=h).text
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert rows[0]["status"] == "interview" and rows[0]["submission_verified"] == "True"

    # analytics excludes simulated by default
    an = client.get("/api/analytics", headers=h).json()
    assert an["counts"]["applications_submitted"] == 0
    an = client.get("/api/analytics?include_simulated=true", headers=h).json()
    assert an["counts"]["applications_submitted"] == 1 and an["counts"]["submissions_verified"] == 1

    # reusable answer is reused on another application
    other = next(j for j in jobs if j["id"] != backend["id"])
    app2 = client.post(f"/api/jobs/{other['id']}/shortlist", headers=h).json()["application_id"]
    q2 = client.post(f"/api/applications/{app2}/questions", headers=h,
                     json={"questions": ["Will you now or in the future require sponsorship?"]}).json()[0]
    assert q2["answer"] == "No" and q2["source"] == "Reused your saved answer"


def test_master_profile_unchanged_by_tailoring(client):
    h, _ = make_user(client)
    before = setup_profile(client, h)
    jobs = _mock_jobs(client, h)
    for j in jobs[:3]:
        client.post(f"/api/jobs/{j['id']}/resume/tailor", headers=h)
    after = client.get("/api/profile", headers=h).json()
    assert after["experience"] == before["experience"] and after["skills"] == before["skills"]


def test_resume_edit_cannot_change_locked_fields(client):
    h, _ = make_user(client)
    setup_profile(client, h)
    j = _mock_jobs(client, h)[0]
    d = client.post(f"/api/jobs/{j['id']}/resume/tailor", headers=h).json()
    d["content"]["experience"][0]["company"] = "Google"
    r = client.put(f"/api/documents/{d['id']}", json={"content": d["content"]}, headers=h)
    assert r.status_code == 400 and "locked" in r.json()["detail"]


def test_authorization_isolation(client):
    ha, _ = make_user(client)
    hb, _ = make_user(client)
    setup_profile(client, ha)
    j = _mock_jobs(client, ha)[0]
    d = client.post(f"/api/jobs/{j['id']}/resume/tailor", headers=ha).json()
    for path in [f"/api/jobs/{j['id']}", f"/api/documents/{d['id']}", f"/api/documents/{d['id']}/download"]:
        assert client.get(path, headers=hb).status_code == 404
    assert client.post(f"/api/jobs/{j['id']}/shortlist", headers=hb).status_code == 404
    assert client.get("/api/jobs", headers=hb).json()["total"] == 0
    assert client.get("/api/jobs").status_code == 401


def test_duplicate_detection_across_real_adapters(client):
    h, _ = make_user(client)
    setup_profile(client, h)
    gh = client.post("/api/sources", json={"kind": "greenhouse", "identifier": "globex"}, headers=h).json()
    lv = client.post("/api/sources", json={"kind": "lever", "identifier": "globex"}, headers=h).json()
    t = transport_for({
        "https://boards-api.greenhouse.io/v1/boards/globex/jobs": (200, GH_PAYLOAD, "application/json"),
        "https://boards-api.greenhouse.io/v1/boards/globex": (200, {"name": "Globex"}, "application/json"),
        "https://api.lever.co/v0/postings/globex": (200, LEVER_PAYLOAD, "application/json"),
    })
    with session_scope() as db:
        assert run_source(db, db.get(JobSource, gh["id"]), transport=t)["new"] == 1
        assert run_source(db, db.get(JobSource, lv["id"]), transport=t)["new"] == 1
        # re-run is idempotent
        assert run_source(db, db.get(JobSource, gh["id"]), transport=t)["unchanged"] == 1
    listed = client.get("/api/jobs", headers=h).json()
    assert listed["total"] == 1  # duplicate hidden
    assert client.get("/api/jobs?include_duplicates=true", headers=h).json()["total"] == 2
    detail = client.get(f"/api/jobs/{listed['items'][0]['id']}", headers=h).json()
    assert detail["duplicates"] and detail["duplicates"][0]["source_kind"] == "lever"
    # listing removed from board → closed, history preserved
    t2 = transport_for({
        "https://boards-api.greenhouse.io/v1/boards/globex/jobs": (200, {"jobs": []}, "application/json"),
        "https://boards-api.greenhouse.io/v1/boards/globex": (200, {"name": "Globex"}, "application/json"),
    })
    with session_scope() as db:
        assert run_source(db, db.get(JobSource, gh["id"]), transport=t2)["closed"] == 1
    assert client.get("/api/jobs?status=closed&include_duplicates=true", headers=h).json()["total"] == 1


def test_source_error_is_reported_not_raised(client):
    h, _ = make_user(client)
    s = client.post("/api/sources", json={"kind": "greenhouse", "identifier": "doesnotexist"}, headers=h).json()
    with session_scope() as db:
        stats = run_source(db, db.get(JobSource, s["id"]), transport=transport_for({}))
    assert "not found" in stats["error"]
    src = client.get("/api/sources", headers=h).json()[0]
    assert src["last_status"] == "error" and "not found" in src["last_error"]


def test_outreach_requires_approval_and_prevents_duplicates(client):
    h, _ = make_user(client)
    setup_profile(client, h)
    j = _mock_jobs(client, h)[0]
    plan = client.get(f"/api/jobs/{j['id']}/research-plan", headers=h).json()
    assert plan["plan"] and all(p["verified"] is False for p in plan["plan"])
    assert "(Demo)" not in plan["plan"][0]["queries"][0]["query"]
    assert client.post("/api/contacts", headers=h, json={"job_id": j["id"], "name": "Sam Lee", "verified": True}).status_code == 400
    c = client.post("/api/contacts", headers=h, json={"job_id": j["id"], "name": "Sam Lee", "role": "Technical Recruiter",
                                                     "contact_type": "recruiter", "verified": True,
                                                     "source_url": "https://www.linkedin.com/in/example"}).json()
    m = client.post(f"/api/contacts/{c['id']}/outreach", headers=h, json={"channel": "linkedin", "kind": "connection"}).json()
    assert len(m["body"]) <= 300 and m["status"] == "draft"
    assert client.post(f"/api/contacts/{c['id']}/outreach", headers=h, json={"channel": "linkedin", "kind": "connection"}).status_code == 409
    assert client.post(f"/api/outreach/{m['id']}/mark-sent", headers=h).status_code == 400
    assert client.post(f"/api/outreach/{m['id']}/approve", json={"confirm": True}, headers=h).status_code == 200
    assert client.post(f"/api/outreach/{m['id']}/mark-sent", headers=h).status_code == 200
    assert client.post(f"/api/outreach/{m['id']}/mark-sent", headers=h).status_code == 409
    tasks = client.get("/api/tasks", headers=h).json()
    assert any("reply from Sam Lee" in t["title"] for t in tasks)


def test_pause_stops_scheduler(client):
    from app import scheduler

    h, email = make_user(client)
    setup_profile(client, h)
    client.post("/api/sources", json={"kind": "mock", "identifier": "pausetest"}, headers=h)
    client.post("/api/automation/pause", headers=h)
    uid = client.get("/api/auth/me", headers=h).json()["id"]
    assert uid not in scheduler.tick()
    client.post("/api/automation/resume", headers=h)
    assert uid in scheduler.tick()
    assert uid not in scheduler.tick()  # interval not elapsed → no duplicate work
    assert client.get("/api/jobs", headers=h).json()["total"] == 5
    client.put("/api/settings", json={"workflows": {"discovery": False}}, headers=h)
    with session_scope() as db:
        db.get(UserSettings, uid).last_auto_search_at = None
    assert uid not in scheduler.tick()


def test_secrets_never_exposed(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-SUPERSECRET-123")
    h, _ = make_user(client)
    for path in ["/api/health", "/api/dashboard", "/api/settings", "/api/account/export"]:
        r = client.get(path, headers=h)
        assert "sk-SUPERSECRET" not in r.text
    assert client.get("/api/health").json()["llm"]["configured"] is True


def test_auth_errors_and_rate_limit(client):
    _, email = make_user(client)
    assert client.post("/api/auth/login", json={"email": email, "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/register", json={"email": email, "password": "correct-horse-1"}).status_code == 409
    assert client.post("/api/auth/register", json={"email": "bad", "password": "x"}).status_code == 422
    codes = [client.post("/api/auth/login", json={"email": email, "password": "wrong-password"}).status_code for _ in range(12)]
    assert 429 in codes


def test_account_export_and_delete(client):
    h, email = make_user(client)
    setup_profile(client, h)
    _mock_jobs(client, h)
    client.post("/api/resumes", headers=h, files={"file": ("cv.docx", sample_docx_bytes(), "application/octet-stream")})
    exp = client.get("/api/account/export", headers=h).json()
    assert exp["candidate_profiles"][0]["full_name"] == "Jordan Rivera" and len(exp["jobs"]) == 5
    assert "storage_name" not in exp["resumes"][0]
    assert client.delete("/api/account?confirm_email=wrong@example.com", headers=h).status_code == 400
    assert client.delete(f"/api/account?confirm_email={email}", headers=h).status_code == 200
    assert client.get("/api/profile", headers=h).status_code == 401


def test_csv_formula_injection_neutralised(client):
    h, _ = make_user(client)
    setup_profile(client, h)
    j = client.post("/api/jobs/manual", headers=h, json={"title": "=HYPERLINK(\"x\")", "company": "Evil", "description_text": "Python"}).json()["job"]
    client.post(f"/api/jobs/{j['id']}/shortlist", headers=h)
    text = client.get("/api/applications/export.csv", headers=h).text
    assert "'=HYPERLINK" in text


def test_profile_patch_keeps_other_fields_and_revisions(client):
    h, _ = make_user(client)
    setup_profile(client, h)
    r = client.patch("/api/profile", json={"headline": "Platform Engineer"}, headers=h).json()
    assert r["headline"] == "Platform Engineer" and r["experience"][0]["company"] == "Acme Corp"
    revs = client.get("/api/profile/revisions", headers=h).json()
    assert len(revs) >= 2
    restored = client.post(f"/api/profile/revisions/{revs[0]['id']}/restore", headers=h).json()
    assert restored["headline"] == "Backend Engineer"


def test_registration_first_mode(client, monkeypatch):
    make_user(client)  # at least one account exists
    monkeypatch.setattr(settings, "registration_mode", "first")
    r = client.post("/api/auth/register", json={"email": "late@example.com", "password": "correct-horse-1"})
    assert r.status_code == 403
    monkeypatch.setattr(settings, "registration_mode", "0")
    assert client.post("/api/auth/register", json={"email": "late@example.com", "password": "correct-horse-1"}).status_code == 403
    monkeypatch.setattr(settings, "registration_mode", "1")
    assert client.post("/api/auth/register", json={"email": "late@example.com", "password": "correct-horse-1"}).status_code == 200
