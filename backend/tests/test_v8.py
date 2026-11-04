"""Resume tailoring v2: AI rewrite → review → guards; no keyword lists tacked onto the summary."""
import httpx

from .test_v2 import _NoDB
from .test_v5 import _full_skills_pdf


class J:
    id, title, company = 1, "Backend Engineer", "Acme"
    description_text = ("Requirements\n- Python, SQL, Docker, Terraform, Jenkins, Grafana and AWS\n- REST APIs and Kubernetes\n"
                        "- Kafka and Spring Boot\n- Bachelor's degree in Computer Science")


class R:
    id, user_id, mime_type, original_filename, storage_name = 1, 1, "pdf", "r.pdf", "x"
    file_data = _full_skills_pdf()


def test_style_guard_catches_keyword_dumps():
    from app.services.tailor_ai import style_problems as sp

    o = "Results-driven engineer with 3 years in backend development. Delivered scalable microservices."
    assert "ends with a tacked-on skills list" in sp(o, o + " Skilled in Java, Kafka, Docker and AWS.", "summary")
    assert any("appends" in p for p in sp(o, o + " Strong focus on cloud and DevOps.", "summary"))
    assert "ends with a list of keywords" in sp(o, "Backend engineer with 3 years of experience. Delivered scalable "
                                                   "microservices. Strong in Java, Python, SQL, Docker and Kubernetes.", "summary")
    assert sp(o, "Backend software engineer with 3 years building Java microservices on Azure and Kubernetes; delivered "
                 "CI/CD pipelines that cut release time by 25%.", "summary") == []
    assert any("too many tools" in p for p in sp("Automated deployments with JBoss.",
                                                 "Automated deployments with JBoss, Docker, Kubernetes, Terraform, Jenkins and AWS.", "bullet"))


def test_no_ai_never_tacks_keywords_onto_summary(monkeypatch):
    from app.services import inplace_pdf, llm, tailor_inplace

    monkeypatch.setattr(llm, "config_for", lambda db, uid: None)
    c, flags, gen = tailor_inplace.build_plan(_NoDB(), 1, J(), R())
    text = inplace_pdf.full_text(tailor_inplace.render(c, R())[0])
    assert "Skilled in" not in text and gen == "rules"
    assert any("connect" in f["message"] for f in flags)


def test_ai_rewrite_review_and_guards(monkeypatch):
    from app.services import inplace_pdf, llm, tailor_inplace

    pdf = R.file_data
    units = {u.text[:12]: u.id for u in inplace_pdf.analyze(pdf)["units"]}
    summ, b1, b2 = units["Software eng"], units["Built paymen"], units["Set up Jenki"]
    calls = []

    def fake(task, payload, schema, *, cfg=None, name="", **k):
        calls.append(name)
        assert "job_skills_missing" in payload and "Kafka" in payload.split("<job_skills_missing>")[1].split("<")[0]
        if name == "tailored_lines":
            return {"items": [
                {"id": summ, "changed": True, "keywords_added": ["AWS", "Docker"], "text":
                    "Backend engineer with 4 years building **Python** APIs on **AWS** with **Docker** for fintech teams, "
                    "cutting latency by 20%."},
                {"id": b1, "changed": True, "keywords_added": ["Kafka"], "text":  # claims a skill the candidate lacks
                    "Built payment REST APIs in Python and Kafka with Docker and Terraform on AWS, cutting latency by 20%."},
                {"id": b2, "changed": True, "keywords_added": [], "text": "Set up Jenkins pipelines and dashboards for 12 services."},
            ]}
        if name == "reviewed_lines":
            return {"items": [{"id": b2, "verdict": "fixed", "text": "Built **Jenkins** CI pipelines and **Grafana** dashboards for 12 services."}]}
        return {"items": []}

    monkeypatch.setattr(llm, "config_for", lambda db, uid: llm.LLMConfig("k", "https://x.test/v1", "m", "openai"))
    monkeypatch.setattr(llm, "complete_json", fake)
    c, flags, gen = tailor_inplace.build_plan(_NoDB(), 1, J(), R())
    by = {e["id"]: e for e in c["units"]}
    assert calls[:2] == ["tailored_lines", "reviewed_lines"] and gen == "ai:m"
    assert by[summ]["status"] == "suggested" and "20%" in by[summ]["final"]  # numbers from the bullets are fine
    assert by[b1]["status"] == "rejected_guard" and "Kafka" in by[b1]["note"]  # never claims a missing skill
    assert by[b2]["status"] == "suggested" and "Grafana" in by[b2]["final"] and "review" in by[b2]["note"]
    assert any("Kafka" in f["message"] for f in flags)  # told which required skills weren't added
    out, _ = tailor_inplace.render(c, R())
    text = inplace_pdf.full_text(out)
    assert "Backend engineer with 4 years" in text and "Kafka" not in text and "Skilled in" not in text
    assert "Sam Lee" in text


def test_ai_failure_keeps_skills_and_explains(monkeypatch):
    from app.services import llm, tailor_inplace

    def busy(*a, **k):
        raise llm.LLMError("The AI service is busy or rate-limited (429). Try again in a minute.")

    monkeypatch.setattr(llm, "config_for", lambda db, uid: llm.LLMConfig("k", "https://x.test/v1", "m", "openai"))
    monkeypatch.setattr(llm, "complete_json", busy)
    c, flags, gen = tailor_inplace.build_plan(_NoDB(), 1, J(), R())
    assert any("AI rewrite unavailable" in f["message"] for f in flags)
    assert any(s["selected"] for s in c["skills"])


def test_capacity_lets_rewrites_use_the_free_space():
    from app.services import inplace_pdf

    pdf = R.file_data
    u = next(u for u in inplace_pdf.analyze(pdf)["units"] if u.text.startswith("Set up Jenkins"))
    cap = inplace_pdf.capacity(pdf, u)
    assert cap > len(u.text) * 1.3  # a short one-line bullet has room to grow
    filler = (u.text + " and more of the same work") * 5
    assert inplace_pdf.fits(pdf, u, [(filler[:cap].rsplit(" ", 1)[0], False)])["fits"]


def test_best_model_prefers_newest_pro_and_falls_back(monkeypatch):
    from app.services import llm

    llm._BEST_MODEL.clear()
    seen = []

    def handler(req):
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "models/gemini-2.5-pro"}, {"id": "models/gemini-3.1-pro"},
                                                      {"id": "models/gemini-3.1-pro-preview-0601"}, {"id": "models/gemini-3.8-flash"}]})
        import json
        model = json.loads(req.content)["model"]
        seen.append(model)
        if model == "gemini-3.1-pro":
            return httpx.Response(429, json={"error": {"message": "quota"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"ok\": true}"}}]})

    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    cfg = llm.LLMConfig("key-abcdef", "https://g.test/v1beta/openai", "gemini-3.8-flash", "gemini")
    t = httpx.MockTransport(handler)
    assert llm.best_model(cfg, t) == "gemini-3.1-pro"
    out, used = llm.complete_json_best("t", "p", llm.strict_schema({"ok": {"type": "boolean"}}), cfg=cfg, transport=t)
    assert out == {"ok": True} and seen[0] == "gemini-3.1-pro" and used == "gemini-3.8-flash" and seen[-1] == "gemini-3.8-flash"
    llm._BEST_MODEL.clear()


def test_ai_key_that_is_an_email_is_refused_and_test_result_is_shown(client, monkeypatch):
    from app.services import llm

    from .conftest import make_user

    h, _ = make_user(client)
    r = client.put("/api/integrations/ai", json={"provider": "gemini", "api_key": "someone.name@gmail.com"}, headers=h)
    assert r.status_code == 400 and "email" in r.json()["detail"] and "AIza" in r.json()["detail"]
    assert client.put("/api/integrations/ai", json={"provider": "gemini", "api_key": "AIzaSyD-abcdefghijklmnopqrstuvwxyz012"},
                      headers=h).json()["tested"] is None  # saved, not tested yet

    def rejected(cfg, transport=None):
        raise llm.LLMError("The AI service rejected the API key. Check it in Settings → Connections.")

    monkeypatch.setattr(llm, "test_connection", rejected)
    assert client.post("/api/integrations/ai/test", headers=h).status_code == 400
    ai = client.get("/api/integrations", headers=h).json()["ai"]
    assert ai["tested"] == "failed" and "rejected" in ai["test_msg"]
    monkeypatch.setattr(llm, "test_connection", lambda cfg, transport=None: "Google Gemini · gemini-3.8-flash")
    assert client.post("/api/integrations/ai/test", headers=h).json()["ok"] is True
    assert client.get("/api/integrations", headers=h).json()["ai"]["tested"] == "ok"


def _approved_app(client, **profile):
    from .conftest import make_user, sample_docx_bytes, setup_profile
    from .test_api import _mock_jobs

    h, _ = make_user(client)
    setup_profile(client, h, **profile)
    client.post("/api/resumes", headers=h, files={"file": ("cv.docx", sample_docx_bytes(), "application/octet-stream")})
    job = _mock_jobs(client, h)[0]
    aid = client.post(f"/api/jobs/{job['id']}/shortlist", headers=h).json()["application_id"]
    assert client.post(f"/api/applications/{aid}/request-approval", headers=h).json()["ok"]
    client.post(f"/api/applications/{aid}/approve", headers=h, json={"confirm": True})
    return h, aid


def test_autofill_never_puts_a_country_into_address_fields(client):
    h, aid = _approved_app(client, full_name="Vijay Kumar Kotta", location="USA",
                           work_authorization={"authorized_countries": ["United States"], "requires_sponsorship": True, "notes": ""})
    P = client.get(f"/api/applications/{aid}/autofill", headers=h).json()["profile"]
    assert (P["first_name"], P["middle_name"], P["last_name"]) == ("Vijay", "Kumar", "Kotta")
    assert P["city"] == "" and P["address_line1"] == "" and P["postal_code"] == "" and P["country"] == "United States"
    # the user's own name parts and address win, and saving the profile without them keeps them
    prof = client.get("/api/profile", headers=h).json()
    body = {k: prof[k] for k in ("full_name", "email", "phone", "location", "headline", "summary", "links", "skills", "experience",
                                 "education", "certifications", "projects", "preferences", "work_authorization")}
    client.put("/api/profile", headers=h, json={**body, "application_details": {
        "first_name": "Vijay Kumar", "last_name": "Kotta", "address_line1": "12 Main St", "city": "Buffalo", "state": "NY",
        "postal_code": "14201", "country": "USA", "willing_to_relocate": True}})
    client.put("/api/profile", headers=h, json=body)  # an older form without application_details
    p = client.get(f"/api/applications/{aid}/autofill", headers=h).json()
    P = p["profile"]
    assert (P["first_name"], P["middle_name"], P["last_name"]) == ("Vijay Kumar", "", "Kotta")
    assert (P["address_line1"], P["city"], P["state"], P["state_code"], P["postal_code"], P["country"]) == \
        ("12 Main St", "Buffalo", "New York", "NY", "14201", "United States")
    assert P["location"] == "Buffalo, New York" and p["details"]["willing_to_relocate"] is True


def test_ai_answers_only_from_facts_and_only_given_options(client, monkeypatch):
    from app.services import llm

    h, aid = _approved_app(client)
    assert client.post(f"/api/applications/{aid}/autofill/answers", headers=h, json={"questions": [
        {"id": "q0", "label": "Why this role?"}]}).json() == {"answers": [], "ai": False}  # no AI: nothing guessed
    seen = {}

    def fake(task, payload, schema, **k):
        seen["payload"] = payload
        return {"answers": [{"id": "q0", "answer": "I build reliable APIs in Python.", "basis": "resume"},
                            {"id": "q1", "answer": "Maybe", "basis": ""},  # not one of the options → dropped
                            {"id": "q2", "answer": "Male", "basis": ""}]}  # EEO questions are never sent or filled

    monkeypatch.setattr(llm, "config_for", lambda db, uid: llm.LLMConfig("k", "https://x.test/v1", "m"))
    monkeypatch.setattr(llm, "complete_json", fake)
    r = client.post(f"/api/applications/{aid}/autofill/answers", headers=h, json={"questions": [
        {"id": "q0", "label": "Why are you interested in this role?", "kind": "long text"},
        {"id": "q1", "label": "Are you willing to work onsite?", "kind": "radio", "options": ["Yes", "No"]},
        {"id": "q2", "label": "Gender", "kind": "select", "options": ["Male", "Female"]}]}).json()
    assert r["ai"] is True and [a["id"] for a in r["answers"]] == ["q0"]
    assert "Gender" not in seen["payload"] and "<candidate_facts>" in seen["payload"]


def test_posting_contacts_are_only_what_the_company_published():
    from app.services.networking import posting_contacts

    class Job:
        description_text = ("Questions? Reach out to our recruiter, Priya Shah (priya.shah@acme.com). Hiring Manager: Daniel Kim. "
                            "For accommodation requests email accommodations@acme.com. Apply at careers@acme.com. "
                            "Equal Opportunity Employer.")

    got = {(c["name"], c["role"], c["email"]) for c in posting_contacts(Job())}
    assert got == {("Priya Shah", "Recruiter", "priya.shah@acme.com"), ("Daniel Kim", "Hiring Manager", ""),
                   ("", "Contact published in the posting", "careers@acme.com")}


def test_outreach_ai_draft_personal_and_guarded(client, monkeypatch):
    from app.services import llm

    from .conftest import make_user, setup_profile
    from .test_api import _mock_jobs

    h, _ = make_user(client)
    setup_profile(client, h, education=[{"institution": "University at Buffalo", "degree": "MS", "field": "Computer Science",
                                         "start": "2025", "end": "2026"}])
    job = _mock_jobs(client, h)[0]
    plan = client.get(f"/api/jobs/{job['id']}/research-plan", headers=h).json()
    assert any(p["contact_type"] == "alumni" and "University at Buffalo" in p["queries"][0]["query"] for p in plan["plan"])
    assert "from_posting" in plan and "guess" in plan["note"]
    c = client.post("/api/contacts", headers=h, json={"job_id": job["id"], "name": "Priya Shah", "role": "Technical Recruiter",
                                                       "contact_type": "recruiter", "email": "priya@acme.example"}).json()
    # no AI: the template, with a placeholder to personalise
    m = client.post(f"/api/contacts/{c['id']}/outreach", headers=h, json={"channel": "email", "kind": "outreach"}).json()
    assert m["generator"] == "template" and "[[ADD" in m["body"]
    client.delete(f"/api/outreach/{m['id']}", headers=h)
    seen = {}

    def fake(task, payload, schema, **k):
        seen["payload"] = payload
        return {"subject": "Backend role at Acme — fellow UB grad",
                "body": "Hi Priya, I saw you recruit for Acme's platform team and I just applied for the backend role. "
                        "I build Python APIs and would love to hear what the team looks for. Thanks, Jordan"}

    monkeypatch.setattr(llm, "config_for", lambda db, uid: llm.LLMConfig("k", "https://x.test/v1", "m"))
    monkeypatch.setattr(llm, "complete_json", fake)
    m = client.post(f"/api/contacts/{c['id']}/outreach", headers=h,
                    json={"channel": "email", "kind": "outreach", "hook": "She posted about the platform team hiring"}).json()
    assert m["generator"] == "ai" and m["subject"].startswith("Backend role") and "[[ADD" not in m["body"]
    assert "platform team hiring" in seen["payload"] and "<untrusted_personal_hook>" in seen["payload"]
    # invented numbers fall back to the template instead of reaching the user as if true
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {"subject": "Hi", "body": "I grew revenue 900% at Acme."})
    m2 = client.post(f"/api/contacts/{c['id']}/outreach", headers=h, json={"channel": "linkedin", "kind": "connection"}).json()
    assert m2["generator"] == "template" and "900" in m2["note"]
