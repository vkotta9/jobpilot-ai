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
