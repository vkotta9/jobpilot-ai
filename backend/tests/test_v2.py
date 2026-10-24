"""Format-preserving tailoring, ATS scoring, keyword job sources, connections."""
import io
import json

import httpx
import pymupdf
import pytest

from app.services import ats, inplace_docx, inplace_pdf, llm, tailor_inplace
from app.services.inplace_pdf import FitError
from app.services.sources import SourceError
from app.services.sources.keyword import AdzunaAdapter, MuseAdapter, RemotiveAdapter, title_matches

from .conftest import make_user, sample_docx_bytes, setup_profile


def latex_like_pdf() -> bytes:
    """A one-page resume laid out like a LaTeX template (Times, bold headings, bullets, skills lines)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    H = A4[1]
    y = H - 50

    def text(x, s, font="Times-Roman", size=10):
        c.setFont(font, size)
        c.drawString(x, y, s)

    text(230, "Asha Rao", "Times-Bold", 17); y -= 20
    text(150, "asha.rao@example.com  —  +1 (555) 010-2000  —  linkedin.com/in/asharao"); y -= 24
    text(43, "Professional Summary", "Times-Bold", 14); y -= 18
    text(43, "Backend engineer with 3 years building cloud services in Python and Java for retail clients."); y -= 20
    text(43, "Work Experience", "Times-Bold", 14); y -= 18
    text(43, "Globex Corp", "Times-Bold"); c.setFont("Times-Roman", 10); c.drawString(110, y, "— Software Engineer, Austin"); y -= 14
    bullets = [
        ["Developed REST services in Java on Azure, improving data flow efficiency by 30% for a major retail",
         "client while migrating legacy systems."],
        ["Automated deployments with Kubernetes and Azure DevOps, reducing release time by 25%."],
        ["Mentored 3 junior developers on code reviews and testing practices."],
    ]
    for b in bullets:
        text(43, "•")
        text(52, b[0]); y -= 12
        for cont in b[1:]:
            text(52, cont); y -= 12
        y -= 1
    y -= 8
    text(43, "Technical Skills", "Times-Bold", 14); y -= 18
    for label, items in [("Programming:", "Python, Java, C"), ("Cloud & Tools:", "Azure, Kubernetes, Git")]:
        c.setFont("Times-Bold", 10); c.drawString(43, y, label)
        w = c.stringWidth(label, "Times-Bold", 10)
        c.setFont("Times-Roman", 10); c.drawString(43 + w + 3, y, items); y -= 12
    y -= 10
    text(43, "Achievements", "Times-Bold", 14); y -= 18
    text(43, "• Winner, campus hackathon 2021."); y -= 12
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------- in-place PDF

def test_pdf_units_detected():
    data = latex_like_pdf()
    units = inplace_pdf.analyze(data)["units"]
    kinds = [(u.kind, u.section) for u in units]
    assert ("paragraph", "summary") in kinds
    assert sum(1 for k in kinds if k == ("bullet", "experience")) == 3
    skills = [u for u in units if u.kind == "skill_line"]
    assert [u.label for u in skills] == ["Programming:", "Cloud & Tools:"]
    # header and achievements are never editable
    assert not any("asha.rao@example.com" in u.text for u in units)
    assert not any(u.section == "achievements" for u in units)
    first = next(u for u in units if u.kind == "bullet")
    assert len(first.lines) == 2 and first.text.startswith("Developed REST services")


def test_pdf_render_preserves_everything_else():
    data = latex_like_pdf()
    units = inplace_pdf.analyze(data)["units"]
    b = [u for u in units if u.kind == "bullet"]
    skills = {u.label: u for u in units if u.kind == "skill_line"}
    new = [("Built REST APIs and microservices in ", False), ("Java", True), (" on ", False), ("Azure", True),
           (", improving data flow efficiency by 30% for a major retail client during a legacy migration.", False)]
    out, warnings = inplace_pdf.render(data, units, {b[0].id: new}, {skills["Cloud & Tools:"].id: ["CI/CD"]})
    before = inplace_pdf.full_text(data)
    after = inplace_pdf.full_text(out)
    assert "asha.rao@example.com  —  +1 (555) 010-2000" in after.replace(" ", " ") or "asha.rao@example.com" in after
    for keep in ["Asha Rao", "Automated deployments with Kubernetes", "Mentored 3 junior developers", "Winner, campus hackathon 2021",
                 "Programming: Python, Java, C"]:
        assert keep in after
    assert "Built REST APIs and microservices" in after and "Developed REST services" not in after
    assert "Azure, Kubernetes, Git, CI/CD" in after
    assert len(before.splitlines()) == len(after.splitlines())  # same number of lines => same layout
    # new text sits in the same place, in the same font family and size
    doc = pymupdf.open(stream=out, filetype="pdf")
    spans = [s for blk in doc[0].get_text("dict")["blocks"] for l in blk.get("lines", []) for s in l["spans"]
             if "microservices" in s["text"] or s["text"].strip() == "Java"]
    assert spans and all(("Times" in s["font"] or "NimbusRom" in s["font"]) and abs(s["size"] - 10) < 0.6 for s in spans)
    assert any(s["flags"] & 16 or "Bold" in s["font"] for s in spans if s["text"].strip() == "Java")
    assert abs(spans[0]["bbox"][0] - b[0].text_x0) < 25


def test_pdf_render_rejects_overflow():
    data = latex_like_pdf()
    units = inplace_pdf.analyze(data)["units"]
    one_line = next(u for u in units if u.kind == "bullet" and len(u.lines) == 1)
    too_long = [("Automated deployments " * 20, False)]
    assert inplace_pdf.fits(data, one_line, too_long)["fits"] is False
    with pytest.raises(FitError):
        inplace_pdf.render(data, units, {one_line.id: too_long}, {})


def test_docx_render_keeps_bold_and_styles():
    data = sample_docx_bytes()
    units = inplace_docx.analyze(data)["units"]
    bullet = next(u for u in units if u.kind == "bullet")
    out, _ = inplace_docx.render(data, units, {bullet.id: [("Shipped ", False), ("Python", True), (" APIs", False)]}, {})
    import docx

    paras = docx.Document(io.BytesIO(out)).paragraphs
    p = next(p for p in paras if p.text == "Shipped Python APIs")
    assert p.style.name == "List Bullet" and [r.bold for r in p.runs if r.text == "Python"] == [True]
    assert any(p.text == "jordan@example.com | +1 555 010 2030 | github.com/jordan" for p in paras)


# ---------------------------------------------------------------- ATS

JD = """Backend Software Engineer
Requirements
- Bachelor's degree in Computer Science
- 3+ years of experience with Java and Python
- Kubernetes, Docker and CI/CD pipelines
- Strong communication skills
Nice to have
- Kafka and Terraform
Benefits
- Free lunch, Docker swag"""


def test_ats_keywords_weighted_and_clean():
    kws = {k.term: k for k in ats.extract_keywords(JD)}
    assert kws["kubernetes"].required and kws["kubernetes"].weight > kws["kafka"].weight
    assert not kws["kafka"].required
    assert "ci/cd" in kws and "ci" not in kws and "cd" not in kws
    assert kws["communication"].kind == "soft"


def test_ats_score_moves_with_resume_content():
    base = "Software Engineer at Acme, Jan 2020 – Present. Python, Java. B.S. Computer Science. Communicated with teams."
    better = base + " Kubernetes, Docker, CI/CD, Kafka."
    s1, s2 = ats.score(base, "Backend Software Engineer", JD), ats.score(better, "Backend Software Engineer", JD)
    assert s2["score"] > s1["score"]
    assert "kubernetes" in s1["missing_required"] and "kubernetes" not in s2["missing"]
    assert s1["breakdown"]["education"]["score"] == 1.0
    assert "communication" in s1["soft_matched"]  # stem match: "communicated"


# ---------------------------------------------------------------- tailoring plan with AI

class _Resume:
    def __init__(self, data, kind="pdf"):
        self.file_data, self.mime_type, self.user_id, self.storage_name = data, kind, 1, "x"
        self.id, self.original_filename = 1, "asha.pdf"


class _Job:
    id, title, company = 1, "Backend Software Engineer", "Initech"
    description_text = JD + "\nAzure experience and REST APIs required. Microservices."


class _NoDB:
    def query(self, *a, **k):
        class Q:
            def filter_by(s, **k): return s
            def one_or_none(s): return None
        return Q()


def test_plan_applies_safe_suggestions_and_rejects_unsafe(monkeypatch):
    data = latex_like_pdf()
    units = inplace_pdf.analyze(data)["units"]
    bullets = [u for u in units if u.kind == "bullet"]
    monkeypatch.setattr(llm, "config_for", lambda db, uid: llm.LLMConfig("k", "https://x", "test-model"))
    calls = {"n": 0}

    def fake(task, payload, schema, **kw):
        calls["n"] += 1
        assert "<untrusted_job_description>" in payload and "Initech" in payload
        return {"items": [
            {"id": bullets[0].id, "changed": True, "text": "Built REST services in **Java** on **Azure**, improving data flow efficiency by 30% for a major retail client during a legacy-system migration."},
            {"id": bullets[1].id, "changed": True, "text": "Automated CI/CD deployments with Kubernetes and Azure DevOps, cutting release time by 60%."},
            {"id": bullets[2].id, "changed": True, "text": "Mentored 3 junior developers " + "on code reviews and testing practices " * 6},
        ]}

    monkeypatch.setattr(llm, "complete_json", fake)
    content, flags, gen = tailor_inplace.build_plan(_NoDB(), 1, _Job(), _Resume(data))
    st = {u["id"]: u for u in content["units"]}
    assert gen == "ai:test-model"
    assert st[bullets[0].id]["status"] == "suggested" and st[bullets[0].id]["accepted"]
    assert st[bullets[1].id]["status"] == "rejected_guard" and not st[bullets[1].id]["accepted"]  # invented 60%
    assert st[bullets[2].id]["status"] == "too_long" and not st[bullets[2].id]["accepted"]
    assert calls["n"] == 2  # one retry asking for shorter text
    skills = {s["term"]: s for s in content["skills"]}
    assert skills["docker"]["evidenced"] is False and skills["docker"]["selected"] is False
    assert skills["ci/cd"]["selected"] is False  # not evidenced in the original resume
    out, _ = tailor_inplace.render(content, _Resume(data))
    text = inplace_pdf.full_text(out)
    assert "Built REST services in Java on Azure" in text and "60%" not in text
    after = tailor_inplace.ats_after(content, out, _Job())
    assert after["score"] >= content["ats_before"]["score"]


def test_plan_without_ai_only_suggests_skills(monkeypatch):
    monkeypatch.setattr(llm, "config_for", lambda db, uid: None)
    content, flags, gen = tailor_inplace.build_plan(_NoDB(), 1, _Job(), _Resume(latex_like_pdf()))
    assert gen == "rules" and all(u["status"] == "unchanged" for u in content["units"])
    assert any("Connect an AI model" in f["message"] for f in flags)
    assert content["skills"]


# ---------------------------------------------------------------- LLM client

def test_llm_downgrades_to_json_mode_when_schema_rejected():
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body["response_format"]["type"])
        if body["response_format"]["type"] == "json_schema":
            return httpx.Response(400, json={"error": {"message": "unsupported"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n{\"ok\": true}\n```"}}]})

    cfg = llm.LLMConfig("k", "https://example.test/v1", "m", "gemini")
    out = llm.complete_json("t", "p", llm.strict_schema({"ok": {"type": "boolean"}}), cfg=cfg, transport=httpx.MockTransport(handler))
    assert out == {"ok": True} and seen == ["json_schema", "json_object"]


def test_llm_bad_key_message():
    cfg = llm.LLMConfig("k", "https://example.test/v1", "m")
    with pytest.raises(llm.LLMError, match="rejected the API key"):
        llm.complete_json("t", "p", {}, cfg=cfg, transport=httpx.MockTransport(lambda r: httpx.Response(401)))


# ---------------------------------------------------------------- keyword job sources

def _mock(payloads):
    def handler(req):
        for prefix, body in payloads.items():
            if str(req.url).startswith(prefix):
                return httpx.Response(200, json=body)
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)


def test_title_matching():
    assert title_matches("Senior Backend Software Engineer", ["Software Engineer"])
    assert not title_matches("Account Executive", ["Software Engineer"])
    assert not title_matches("Staff Controls Engineer", ["Software Engineer"])
    assert title_matches("Machine Learning Engineer, Platform", ["Senior Machine Learning Engineer"])


def test_adzuna_adapter_and_predicted_salary():
    body = {"results": [{"id": "123", "title": "<strong>Software Engineer</strong>", "company": {"display_name": "Initech"},
                         "location": {"display_name": "Buffalo, NY"}, "description": "Build Java services…",
                         "redirect_url": "https://www.adzuna.com/details/123", "created": "2026-10-20T10:00:00Z",
                         "salary_min": 90000, "salary_max": 120000, "salary_is_predicted": "1", "contract_time": "full_time"}]}
    ctx = {"queries": ["Software Engineer"], "locations": ["Buffalo, NY"], "credentials": {"app_id": "a", "app_key": "b"}}
    jobs = AdzunaAdapter("auto", context=ctx, transport=_mock({"https://api.adzuna.com/v1/api/jobs/us/search/1": body}),
                         sleep=lambda s: None).fetch()
    assert len(jobs) == 1 and jobs[0].title == "Software Engineer" and jobs[0].salary_min is None
    with pytest.raises(SourceError, match="connect your free Adzuna key"):
        AdzunaAdapter("auto", context={**ctx, "credentials": {}}).fetch()


def test_remotive_and_muse_adapters():
    rem = {"jobs": [{"id": 9, "title": "Python Software Engineer", "company_name": "Acme", "url": "https://remotive.com/remote-jobs/9",
                     "candidate_required_location": "USA", "description": "<p>Python</p>", "publication_date": "2026-10-20T00:00:00",
                     "category": "Software Development", "job_type": "full_time", "salary": "$120k"},
                    {"id": 10, "title": "Sales Manager", "company_name": "Acme", "url": "u"}]}
    muse = {"page": 0, "page_count": 1, "results": [
        {"id": 77, "name": "Software Engineer II", "company": {"name": "Muse Co"}, "locations": [{"name": "Flexible / Remote"}],
         "refs": {"landing_page": "https://www.themuse.com/jobs/museco/se"}, "contents": "<p>Go and Java</p>",
         "publication_date": "2026-10-19T00:00:00Z"},
        {"id": 78, "name": "Office Manager", "company": {"name": "Muse Co"}, "locations": [], "refs": {}}]}
    ctx = {"queries": ["Software Engineer"], "locations": [], "credentials": {}}
    r = RemotiveAdapter("auto", context=ctx, transport=_mock({"https://remotive.com/api/remote-jobs": rem}), sleep=lambda s: None).fetch()
    assert [j.external_id for j in r] == ["9"] and r[0].remote_type == "remote" and "via Remotive" in r[0].description_text
    m = MuseAdapter("auto", context=ctx, transport=_mock({"https://www.themuse.com/api/public/jobs": muse}), sleep=lambda s: None).fetch()
    assert [j.external_id for j in m] == ["77"] and m[0].url.startswith("https://www.themuse.com/")


def test_keyword_source_never_closes_and_respects_interval(client):
    from app.db import session_scope
    from app.models import Job, JobSource
    from app.services.discovery import run_source

    h, _ = make_user(client)
    setup_profile(client, h)
    uid = client.get("/api/auth/me", headers=h).json()["id"]
    rem1 = {"jobs": [{"id": 1, "title": "Backend Engineer", "company_name": "A", "url": "https://remotive.com/1", "description": "x"}]}
    rem2 = {"jobs": []}
    with session_scope() as db:
        src = JobSource(user_id=uid, kind="remotive", identifier="auto")
        db.add(src)
        db.flush()
        sid = src.id
    with session_scope() as db:
        s = run_source(db, db.get(JobSource, sid), transport=_mock({"https://remotive.com/api/remote-jobs": rem1}))
        assert s["new"] == 1
    with session_scope() as db:
        s = run_source(db, db.get(JobSource, sid), transport=_mock({"https://remotive.com/api/remote-jobs": rem2}))
        assert "skipped" in s  # Remotive: max a few calls per day
        db.get(JobSource, sid).last_run_at = None
    with session_scope() as db:
        s = run_source(db, db.get(JobSource, sid), transport=_mock({"https://remotive.com/api/remote-jobs": rem2}))
        assert s["closed"] == 0
        assert db.query(Job).filter_by(user_id=uid, source_kind="remotive").one().listing_status == "active"


# ---------------------------------------------------------------- connections API

def test_integrations_are_encrypted_masked_and_not_exported(client):
    from app.db import session_scope
    from app.models import IntegrationSetting

    h, _ = make_user(client)
    r = client.put("/api/integrations/ai", json={"provider": "gemini", "api_key": "AIzaSECRETKEY123456"}, headers=h)
    assert r.status_code == 200 and r.json()["configured"] and r.json()["key_hint"] == "••••3456"
    assert r.json()["model"] == llm.PRESETS["gemini"]["model"]
    with session_scope() as db:
        row = db.query(IntegrationSetting).filter_by(provider="ai").order_by(IntegrationSetting.id.desc()).first()
        assert "AIzaSECRET" not in row.data_encrypted
    for path in ["/api/integrations", "/api/account/export", "/api/health", "/api/dashboard"]:
        assert "AIzaSECRETKEY" not in client.get(path, headers=h).text
    # keep the key when saving again without one
    assert client.put("/api/integrations/ai", json={"provider": "gemini", "model": "gemini-3.6-flash"}, headers=h).json()["model"] == "gemini-3.6-flash"
    assert client.put("/api/integrations/adzuna", json={"app_id": "x"}, headers=h).status_code == 400
    assert client.put("/api/integrations/adzuna", json={"app_id": "id1", "app_key": "key1"}, headers=h).json()["configured"]
    assert client.delete("/api/integrations/ai", headers=h).status_code == 200
    assert client.get("/api/integrations", headers=h).json()["ai"]["configured"] is False


def test_auto_search_requires_titles_and_paste_description(client):
    h, _ = make_user(client)
    setup_profile(client, h, preferences={"target_titles": []}, experience=[], headline="")
    assert client.post("/api/discovery/auto", json={"kinds": ["remotive"]}, headers=h).status_code == 400
    setup_profile(client, h)
    st = client.get("/api/discovery/auto", headers=h).json()
    kinds = {s["kind"] for s in st["sources"]}
    assert st["queries"] == ["Backend Engineer"] and {"remotive", "muse", "himalayas", "jobicy", "jsearch", "usajobs"} <= kinds
    j = client.post("/api/jobs/manual", headers=h, json={"title": "Backend Engineer", "company": "X", "description_text": "short"}).json()["job"]
    full = "Requirements\n- 3+ years with Python, FastAPI, PostgreSQL, Docker, AWS and Redis\n- Bachelor's degree in Computer Science\n" * 3
    r = client.put(f"/api/jobs/{j['id']}/description", json={"description_text": full}, headers=h)
    assert r.status_code == 200 and r.json()["score"] > 0
