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


def _skills_pdf():
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = letter[1] - 50

    def t(x, s, f="Times-Roman", z=10):
        c.setFont(f, z)
        c.drawString(x, y, s)

    t(240, "Alex Kim", "Times-Bold", 17); y -= 22
    t(43, "Summary", "Times-Bold", 14); y -= 16; t(43, "Software engineer building backend services and ML pipelines."); y -= 20
    t(43, "Experience", "Times-Bold", 14); y -= 16
    for b in ["Built REST APIs in Python and Node.js for a payments platform, serving 2M requests a day.",
              "Collaborated with product and design teams to ship features every sprint."]:
        t(43, "•"); t(52, b); y -= 13
    y -= 8; t(43, "Technical Skills", "Times-Bold", 14); y -= 16
    for label, items in [("Languages:", "Python, Java, JavaScript, TypeScript"), ("AI/ML:", "PyTorch, TensorFlow, scikit-learn"),
                         ("Web:", "React, HTML, CSS, PHP"), ("Databases:", "PostgreSQL, MySQL, Oracle")]:
        c.setFont("Times-Bold", 10); c.drawString(43, y, label); w = c.stringWidth(label, "Times-Bold", 10)
        c.setFont("Times-Roman", 10); c.drawString(43 + w + 3, y, items); y -= 12
    c.save()
    return buf.getvalue()


def test_plain_language_requests_without_ai(monkeypatch):
    from app.services import inplace_pdf, llm, tailor_inplace, tailor_request

    from .test_v2 import _NoDB

    monkeypatch.setattr(llm, "config_for", lambda db, uid: None)
    pdf = _skills_pdf()

    class J:
        id, title, company = 1, "Backend Engineer", "Acme"
        description_text = "Requirements\n- Python, Node.js, PostgreSQL"

    class R:
        id, user_id, mime_type, original_filename, storage_name = 1, 1, "pdf", "r.pdf", "x"
        file_data = pdf

    c, _, _ = tailor_inplace.build_plan(_NoDB(), 1, J(), R())

    def ask(text):
        nonlocal c
        c, res = tailor_request.apply_request(_NoDB(), 1, c, R(), J(), text)
        return res

    ask("Add Node.js to AI/ML")
    res = ask("No please remove Node.js from AI/Ml and add that in the Language that too at the end means after TypeScript")
    assert len(res["done"]) == 2 and not res["skipped"], res
    ask("remvoe php form web skils")  # typos
    ask("ad kubernets and docker to languages at the start")
    ask("move PyTorch to the end")
    ask("replace Oracle with SQLite")
    ask('In the line "Collaborated with product": add the keyword cross-functional')
    assert "Didn't understand" in ask("make it sound more senior")["skipped"][0]
    text = inplace_pdf.full_text(tailor_inplace.render(c, R())[0])
    assert "Languages: Kubernetes, Docker, Python, Java, JavaScript, TypeScript, Node.js" in text
    assert "AI/ML: TensorFlow, scikit-learn, PyTorch" in text
    assert "Web: React, HTML, CSS" in text and "PHP" not in text
    assert "Databases: PostgreSQL, MySQL, SQLite" in text
    assert "with cross-functional product and design teams" in text


def test_ai_rate_limit_waits_then_switches_model(monkeypatch):
    import httpx

    from app.services import llm

    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    seen = []

    def handler(req):
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "models/gemini-x-flash"}, {"id": "models/gemini-x-flash-lite"}]})
        body = json.loads(req.content)
        seen.append(body["model"])
        if body["model"] == "gemini-x-flash":
            return httpx.Response(429, json={"error": {"message": "quota", "details": [{"retryDelay": "3s"}]}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"ok\": true}"}}]})

    cfg = llm.LLMConfig("k-123456", "https://g.test/v1beta/openai", "gemini-x-flash", "gemini")
    out = llm.complete_json("t", "p", llm.strict_schema({"ok": {"type": "boolean"}}), cfg=cfg, transport=httpx.MockTransport(handler))
    assert out == {"ok": True} and seen[0] == "gemini-x-flash" and seen[-1] == "gemini-x-flash-lite"


def test_interview_prep_plan(client, monkeypatch):
    from app.services import interview_prep, llm

    from .test_api import _mock_jobs

    h, _ = make_user(client)
    setup_profile(client, h)
    client.post("/api/resumes", headers=h, files={"file": ("cv.docx", sample_docx_bytes(), "application/octet-stream")})
    job = _mock_jobs(client, h)[0]
    aid = client.post(f"/api/jobs/{job['id']}/shortlist", headers=h).json()["application_id"]
    p = client.get(f"/api/applications/{aid}/prep", headers=h).json()["prep"]
    assert p["role"]["family"] in interview_prep.FAMILY_NAMES and len(p["stages"]) >= 3
    assert p["focus"] and all(f["resources"] and f["questions"] for f in p["focus"])
    assert all(r["url"].startswith("https://") for f in p["focus"] for r in f["resources"])
    assert len(p["behavioral"]) == 9 and any(b["story"] for b in p["behavioral"])  # stories from the resume
    assert p["plan"] and p["ask_them"]
    # progress is saved
    first = p["plan"][0]["id"]
    assert client.put(f"/api/applications/{aid}/prep/progress", headers=h, json={"done": [first, "bogus"]}).json()["done"] == [first]
    assert client.get(f"/api/applications/{aid}/prep", headers=h).json()["prep"]["done"] == [first]
    # AI-written questions for this posting
    monkeypatch.setattr(llm, "config_for", lambda db, uid: llm.LLMConfig("k", "https://x.test/v1", "m"))
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {"questions": [
        {"question": "How would you design an idempotent payments API?", "type": "design", "why_likely": "Posting: REST APIs",
         "strong_answer_covers": "idempotency keys, retries", "use_from_resume": "payments API"}]})
    p = client.post(f"/api/applications/{aid}/prep", headers=h, json={"use_ai": True}).json()["prep"]
    assert p["ai_questions"][0]["type"] == "design" and p["done"] == [first]


def test_prep_knows_company_guides_and_role_families():
    from app.services import interview_prep as ip

    class J:
        title, company = "Senior Data Scientist", "Amazon"
        description_text = "Requirements\n- 5+ years\n- SQL, Python, statistics, A/B testing"

    p = ip.build(J(), "", None, [])
    assert p["role"]["family"] == "data_sci" and p["role"]["level"] == "senior"
    assert p["company"]["url"].startswith("https://www.amazon.jobs/") and any("SQL" in s["name"] for s in p["stages"])
    assert {"sql", "statistics"} <= {f["key"] for f in p["focus"]}
    assert ip.family_of("Site Reliability Engineer", "") == "devops" and ip.level_of("Software Engineer I", None) == "entry"
