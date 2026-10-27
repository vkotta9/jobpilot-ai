"""Browser extension: connect, autofill payload (approval required), submission record, templated download."""
import base64
import io
import json
import zipfile

from .conftest import make_user, sample_docx_bytes, setup_profile


def test_extension_connect_and_ping(client):
    h, email = make_user(client)
    t = client.post("/api/extension/connect", headers=h).json()
    assert t["token"] and t["expires_in_days"] == 180
    assert client.get("/api/extension/ping", headers={"Authorization": "Bearer " + t["token"]}).json()["email"] == email


def test_autofill_needs_approval_then_returns_profile_resume_and_answers(client):
    from .test_api import _mock_jobs

    h, _ = make_user(client)
    setup_profile(client, h, links=["https://linkedin.com/in/jordan", "https://github.com/jordan"],
                  work_authorization={"authorized_countries": ["United States"], "requires_sponsorship": False, "notes": ""})
    client.post("/api/resumes", headers=h, files={"file": ("cv.docx", sample_docx_bytes(), "application/octet-stream")})
    job = _mock_jobs(client, h)[0]
    aid = client.post(f"/api/jobs/{job['id']}/shortlist", headers=h).json()["application_id"]
    qs = client.post(f"/api/applications/{aid}/questions", headers=h, json={"questions": ["Why this company?"]}).json()
    client.put(f"/api/answers/{qs[0]['id']}", headers=h, json={"answer": "Because of the API work.", "approve": True})
    assert client.get(f"/api/applications/{aid}/autofill", headers=h).status_code == 400  # not approved yet
    assert client.post(f"/api/applications/{aid}/request-approval", headers=h).json()["ok"]
    client.post(f"/api/applications/{aid}/approve", headers=h, json={"confirm": True})
    p = client.get(f"/api/applications/{aid}/autofill", headers=h).json()
    assert p["profile"]["first_name"] == "Jordan" and p["profile"]["last_name"] == "Rivera"
    assert p["profile"]["linkedin"].startswith("https://linkedin.com") and p["profile"]["github"].startswith("https://github.com")
    assert p["profile"]["city"] == "New York" and p["work_auth"]["requires_sponsorship"] is False
    assert p["answers"] == [{"question": "Why this company?", "answer": "Because of the API work.", "category": "general"}]
    assert p["resume"]["filename"] == "Jordan_Rivera_Resume.docx" and base64.b64decode(p["resume"]["base64"])[:2] == b"PK"
    # the extension saw the site's confirmation page after you pressed Submit
    r = client.post(f"/api/applications/{aid}/extension-submitted", headers=h,
                    json={"confirmation_detail": "Thank you for applying! Confirmation #A-1", "page_url": "https://boards.example/thanks"}).json()
    assert r["ok"] and r["verified"]
    a = client.get(f"/api/applications/{aid}", headers=h).json()
    assert a["status"] == "applied" and a["submission_method"] == "extension_autofill"
    assert client.get(f"/api/applications/{aid}/autofill", headers=h).status_code == 409  # no double applying
    assert client.post(f"/api/applications/{aid}/extension-submitted", headers=h, json={}).status_code == 409


def test_extension_zip_is_set_up_for_this_site(client):
    r = client.get("/api/extension/jobpilot-extension.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"manifest.json", "filler.js", "background.js"} <= names
    m = json.loads(z.read("manifest.json"))
    assert m["content_scripts"][0]["matches"] == ["http://testserver/*"] and m["manifest_version"] == 3
    assert b'"http://testserver"' in z.read("config.js")


def _tailored_doc(client, h):
    from .test_api import _mock_jobs

    setup_profile(client, h)
    client.post("/api/resumes", headers=h, files={"file": ("cv.docx", sample_docx_bytes(), "application/octet-stream")})
    job = _mock_jobs(client, h)[0]
    return client.post(f"/api/jobs/{job['id']}/resume/tailor", headers=h).json()


def test_change_request_with_rules(client, monkeypatch):
    from app.services import llm

    monkeypatch.setattr(llm, "config_for", lambda db, uid: None)
    h, _ = make_user(client)
    d = _tailored_doc(client, h)
    req = "Add Node.js and GraphQL to my skills\nReplace FastAPI with Starlette\nmake it sound amazing"
    r = client.post(f"/api/documents/{d['id']}/request-change", headers=h, json={"request": req})
    assert r.status_code == 200, r.text
    res, doc = r.json()["result"], r.json()["document"]
    assert any("Node.js" in x for x in res["done"]) and any("GraphQL" in x for x in res["done"])
    assert any("Starlette" in x for x in res["done"])
    assert any("make it sound amazing" in x for x in res["skipped"])  # not understood → said so, nothing invented
    assert doc["status"] == "draft" and doc["content"]["requests"][-1]["via"] == "rules"
    added = [s for s in doc["content"]["skills"] if s.get("user")]
    assert {"Node.js", "GraphQL"} <= {s["display"] for s in added}
    # the rendered file has the changes
    from app.services import inplace_docx
    raw = client.get(f"/api/documents/{d['id']}/download?format=docx", headers=h).content
    text = inplace_docx.full_text(raw)
    assert "Node.js" in text and "GraphQL" in text and "Starlette" in text


def test_change_request_uses_ai_when_connected(client, monkeypatch):
    from app.services import llm

    h, _ = make_user(client)
    d = _tailored_doc(client, h)
    b = next(u for u in d["content"]["units"] if u["kind"] == "bullet")
    sl = next(u for u in d["content"]["units"] if u["kind"] == "skill_line")
    seen = {}
    monkeypatch.setattr(llm, "config_for", lambda db, uid: llm.LLMConfig("k", "https://x.test/v1", "test-model"))

    def fake(task, payload, schema, cfg=None, name=""):
        seen["payload"] = payload
        return {"edits": [{"id": b["id"], "text": b["final"].rstrip(".") + " with cross-functional teams."}],
                "add_skills": [{"line_id": sl["id"], "skill": "Node.js"}], "remove_skills": [], "not_done": []}

    monkeypatch.setattr(llm, "complete_json", fake)
    r = client.post(f"/api/documents/{d['id']}/request-change", headers=h,
                    json={"request": "Add Node.js to Backend skills and add cross-functional to my first bullet"}).json()
    assert "<request>" in seen["payload"] and "<untrusted_job_description>" in seen["payload"]
    units = {u["id"]: u for u in r["document"]["content"]["units"]}
    assert units[b["id"]]["status"] == "requested" and "cross-functional" in units[b["id"]]["final"]
    assert r["result"]["via"] == "ai:test-model" and len(r["result"]["done"]) == 2
