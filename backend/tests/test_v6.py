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
