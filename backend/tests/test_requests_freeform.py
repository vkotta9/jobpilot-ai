"""Change requests in people's own words: the skill lands on the right line, junk never becomes a skill."""
import io

import pytest

from app.services import inplace_pdf, llm, tailor_inplace, tailor_request

from .test_v2 import _NoDB

LINES = [("Languages:", "Java, Python, SQL, JavaScript"), ("Backend & Software Engineering:", "Testing, Microservices, Apache Camel"),
         ("Databases:", "MySQL, Oracle, PostgreSQL"), ("Cloud & DevOps:", "Microsoft Azure, Kubernetes, AWS, JBoss, Git"),
         ("Operating Systems:", "Windows, Linux"), ("AI/ML:", "PyTorch, Machine Learning, Deep Learning")]


def _pdf():
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = letter[1] - 50
    c.setFont("Times-Bold", 17); c.drawString(240, y, "Sam Lee"); y -= 22
    c.setFont("Times-Bold", 14); c.drawString(43, y, "Experience"); y -= 16
    c.setFont("Times-Roman", 10); c.drawString(43, y, "•"); c.drawString(52, y, "Built REST APIs in Java for a payments platform."); y -= 20
    c.setFont("Times-Bold", 14); c.drawString(43, y, "Technical Skills"); y -= 16
    for label, items in LINES:
        c.setFont("Times-Bold", 10); c.drawString(43, y, label); w = c.stringWidth(label, "Times-Bold", 10)
        c.setFont("Times-Roman", 10); c.drawString(43 + w + 3, y, items); y -= 12
    c.save()
    return buf.getvalue()


class J:
    id, title, company = 1, "Platform Engineer", "Acme"
    description_text = "Requirements\n- Java, Kubernetes, Terraform"


class R:
    id, user_id, mime_type, original_filename, storage_name = 1, 1, "pdf", "r.pdf", "x"
    file_data = _pdf()


def _run(monkeypatch, *requests):
    monkeypatch.setattr(llm, "config_for", lambda db, uid: None)
    c, _, _ = tailor_inplace.build_plan(_NoDB(), 1, J(), R())
    res = None
    for text in requests:
        c, res = tailor_request.apply_request(_NoDB(), 1, c, R(), J(), text)
    out = inplace_pdf.full_text(tailor_inplace.render(c, R())[0])
    line = {lab: next(l for l in out.splitlines() if l.startswith(lab)) for lab, _ in LINES}
    return res, line


@pytest.mark.parametrize("text", [
    "add Tearform as a skill to the Devops",      # the reported request: typo + "as a skill"
    "add terraform as a devops skill",
    "can you please add terraform in my cloud and devops skills",
    "put terraform under DevOps section",
    "devops: add terraform",
    "in devops add Terraform",
    "for the cloud line, add Terraform",
    "I know terraform, add it to devops",
    "add Terraform",                                # no line named: goes where it belongs
])
def test_add_skill_any_phrasing(monkeypatch, text):
    res, line = _run(monkeypatch, text)
    assert "Terraform" in line["Cloud & DevOps:"], (res, line)
    assert "as a" not in line["Cloud & DevOps:"] and "skill" not in line["Cloud & DevOps:"].split(":", 1)[1].lower()
    assert "Terraform" not in line["AI/ML:"] and not res["skipped"], res


def test_several_and_shorthand(monkeypatch):
    res, line = _run(monkeypatch, "plz ad helm n ansible to devops")
    assert "Helm" in line["Cloud & DevOps:"] and "Ansible" in line["Cloud & DevOps:"], (res, line)


def test_junk_never_becomes_a_skill(monkeypatch):
    res, line = _run(monkeypatch, "add Developing to AI/ML")
    assert "Developing" not in line["AI/ML:"] and res["skipped"], res


def test_unknown_line_is_asked_not_guessed(monkeypatch):
    res, line = _run(monkeypatch, "add Terraform to my blockchain line")
    assert all("Terraform" not in v for v in line.values())
    assert any("Cloud & DevOps" in s for s in res["skipped"]), res  # lists the real lines


def test_from_it_refers_to_the_line_just_named(monkeypatch):
    res, line = _run(monkeypatch, "add Helm to devops and remove JBoss from it")
    assert "Helm" in line["Cloud & DevOps:"] and "JBoss" not in line["Cloud & DevOps:"], (res, line)


def test_ai_plan_is_cleaned_too(monkeypatch):
    """With an AI key the model plans the ops, and the same checks still apply to what it returns."""
    from types import SimpleNamespace
    monkeypatch.setattr(llm, "config_for", lambda db, uid: None)
    c, _, _ = tailor_inplace.build_plan(_NoDB(), 1, J(), R())
    monkeypatch.setattr(llm, "config_for", lambda db, uid: SimpleNamespace(provider="gemini", model="x", api_key="k"))

    def fake_plan(cfg, request, content, units, job):
        lines = tailor_request.current_skill_lines(content, units)
        dev = next(l["id"] for l in lines if "DevOps" in l["label"])
        ai = next(l["id"] for l in lines if "AI/ML" in l["label"])
        return ([{"op": "add_skill", "skill": "Tearform as a skill", "line_id": dev, "position": None, "req": request},
                 {"op": "add_skill", "skill": "Developing", "line_id": ai, "position": None, "req": request}],
                [], "ai", "")

    monkeypatch.setattr(tailor_request, "_llm_plan", fake_plan)
    c, res = tailor_request.apply_request(_NoDB(), 1, c, R(), J(), "add Tearform as a skill to the Devops")
    out = inplace_pdf.full_text(tailor_inplace.render(c, R())[0])
    dev_line = next(l for l in out.splitlines() if l.startswith("Cloud & DevOps:"))
    ai_line = next(l for l in out.splitlines() if l.startswith("AI/ML:"))
    assert c["requests"][-1]["via"] == "ai"
    assert "Terraform" in dev_line and "as a" not in dev_line and "Developing" not in ai_line, (res, out)


# ---------------------------------------------------------------- preview → confirm → undo, through the API

def _doc(client, monkeypatch):
    from .test_api import make_user
    from .test_v6 import _tailored_doc

    monkeypatch.setattr(llm, "config_for", lambda db, uid: None)
    h, _ = make_user(client)
    return h, _tailored_doc(client, h)


def test_preview_changes_nothing_until_confirmed(client, monkeypatch):
    h, d = _doc(client, monkeypatch)
    before = client.get(f"/api/documents/{d['id']}", headers=h).json()["content"]
    r = client.post(f"/api/documents/{d['id']}/request-change", headers=h,
                    json={"request": "Add GraphQL to my skills", "preview": True})
    assert r.status_code == 200, r.text
    p = r.json()["preview"]
    assert p["token"] and p["changes"] and "GraphQL" in p["changes"][0]["after"] and "GraphQL" not in p["changes"][0]["before"]
    now = client.get(f"/api/documents/{d['id']}", headers=h).json()["content"]
    assert now["skills"] == before["skills"] and len(now.get("requests") or []) == len(before.get("requests") or [])
    assert "pending_change" not in now and "undo" not in now  # never sent to the page

    assert client.post(f"/api/documents/{d['id']}/request-change/confirm", headers=h, json={"token": "wrong-token-123"}).status_code == 409
    r = client.post(f"/api/documents/{d['id']}/request-change/confirm", headers=h, json={"token": p["token"]})
    assert r.status_code == 200, r.text
    doc = r.json()["document"]
    assert any(s["display"] == "GraphQL" and s["selected"] for s in doc["content"]["skills"]) and doc["content"]["can_undo"]
    assert client.post(f"/api/documents/{d['id']}/request-change/confirm", headers=h, json={"token": p["token"]}).status_code == 409

    r = client.post(f"/api/documents/{d['id']}/undo", headers=h)
    assert r.status_code == 200, r.text
    back = r.json()["document"]["content"]
    assert not any(s["display"] == "GraphQL" and s.get("selected") for s in back["skills"])
    assert back["requests"][-1]["via"] == "undo" and not back.get("can_undo")
    assert client.post(f"/api/documents/{d['id']}/undo", headers=h).status_code == 400


def test_cancel_drops_the_preview(client, monkeypatch):
    h, d = _doc(client, monkeypatch)
    p = client.post(f"/api/documents/{d['id']}/request-change", headers=h,
                    json={"request": "Add GraphQL to my skills", "preview": True}).json()["preview"]
    assert client.post(f"/api/documents/{d['id']}/request-change/cancel", headers=h).status_code == 200
    assert client.post(f"/api/documents/{d['id']}/request-change/confirm", headers=h, json={"token": p["token"]}).status_code == 409


def test_unclear_line_offers_choices(monkeypatch):
    monkeypatch.setattr(llm, "config_for", lambda db, uid: None)
    c, _, _ = tailor_inplace.build_plan(_NoDB(), 1, J(), R())
    c, res = tailor_request.apply_request(_NoDB(), 1, c, R(), J(), "add Terraform to my blockchain line")
    assert res["question"] and res["choices"][0] == "Add Terraform to Cloud & DevOps" and not res["changes"]


def test_ai_question_makes_no_change(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(llm, "config_for", lambda db, uid: None)
    c, _, _ = tailor_inplace.build_plan(_NoDB(), 1, J(), R())
    monkeypatch.setattr(llm, "config_for", lambda db, uid: SimpleNamespace(provider="gemini", model="x", api_key="k"))
    monkeypatch.setattr(tailor_request, "_llm_plan", lambda *a: ([], [], "ai:x", "", {
        "question": "Cloud & DevOps or Operating Systems?", "choices": ["Add AWS to Cloud & DevOps", "Add AWS to Operating Systems"]}))
    c, res = tailor_request.apply_request(_NoDB(), 1, c, R(), J(), "add aws somewhere sensible")
    assert res["question"].startswith("Cloud") and len(res["choices"]) == 2 and not res["done"] and not res["changes"]


def test_track_takes_up_to_30_titles(client):
    from .test_api import make_user

    h, _ = make_user(client)
    titles = [f"Engineer {i}" for i in range(30)]
    r = client.post("/api/tracks", headers=h, json={"family": "custom", "name": "Wide", "target_titles": titles})
    assert r.status_code == 200, r.text and r.json()["target_titles"] == titles
    assert r.json()["target_titles"] == titles
    r = client.post("/api/tracks", headers=h, json={"family": "custom", "name": "Too wide", "target_titles": titles + ["One more"]})
    assert r.status_code == 400 and "30" in r.json()["detail"]


def test_stale_scores_refresh_and_poor_fits_sort_last(client):
    """A role two levels above you never sits at the top of 'best match', even if scored by an older model."""
    from app.db import SessionLocal
    from app.models import Job, MatchAssessment

    from .test_api import _mock_jobs, make_user, setup_profile

    h, _ = make_user(client)
    setup_profile(client, h)
    items = _mock_jobs(client, h)
    with SessionLocal() as db:
        j = db.get(Job, items[0]["id"])
        j.title = "Principal Software Engineer – Backend"
        uid = j.user_id
        # pretend an older scoring model gave it 99 and no level penalty
        m = db.query(MatchAssessment).filter_by(job_id=j.id).order_by(MatchAssessment.id.desc()).first()
        m.score, m.fit, m.scoring_version = 99, "good", 1
        db.commit()
    got = client.get("/api/jobs?sort=score&fit=", headers=h).json()["items"]
    top = next(x for x in got if x["id"] == items[0]["id"])
    assert top["match"]["score"] < 99 and top["match"]["fit"] == "poor", top["match"]["score"]
    fits = [x["match"]["fit"] for x in got if x.get("match")]
    assert fits == sorted(fits, key=lambda f: f == "poor")  # every poor fit after every other role


def test_wrapped_skills_line_is_one_line(monkeypatch):
    """'…, Algorithms, Object-' / 'Oriented Programming (OOP)': additions never split the hyphenated word."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 720
    c.setFont("Times-Bold", 13); c.drawString(36, y, "Technical Skills"); y -= 15
    rows = [("Languages:", ["Java, Python, SQL, JavaScript, TypeScript, C"]),
            ("Backend:", ["Microservices, REST APIs, Apache Camel, Message Queues (Azure Service Bus), Data Structures, Algorithms, Object-",
                          "Oriented Programming (OOP)"]),
            ("Cloud & DevOps:", ["Microsoft Azure, Azure DevOps, AWS, Kubernetes, Docker, CI/CD, GitHub Actions, Git, Splunk, Grafana,",
                                 "Geneva, Agile/Scrum."])]
    for lab, parts in rows:
        c.setFont("Times-Bold", 10.5); c.drawString(36, y, lab); w = c.stringWidth(lab, "Times-Bold", 10.5)
        c.setFont("Times-Roman", 10.5); c.drawString(36 + w + 3, y, parts[0]); y -= 12.5
        for r in parts[1:]:
            c.drawString(36, y, r); y -= 12.5
    c.setFont("Times-Bold", 13); c.drawString(36, y - 4, "Experience"); y -= 20
    c.setFont("Times-Roman", 10.5); c.drawString(36, y, "•"); c.drawString(46, y, "Built Java services for payments.")
    c.save()

    class RW(R):
        file_data = buf.getvalue()

    monkeypatch.setattr(llm, "config_for", lambda db, uid: None)
    content, _, _ = tailor_inplace.build_plan(_NoDB(), 1, J(), RW())
    lines = [u for u in content["units"] if u["kind"] == "skill_line"]
    assert len(lines) == 3 and lines[1]["original"].endswith("Object-Oriented Programming (OOP)")
    content, res = tailor_request.apply_request(_NoDB(), 1, content, RW(), J(),
                                                "add GraphQL and System Integrations to backend, add Terraform to devops")
    out = " ".join(inplace_pdf.full_text(tailor_inplace.render(content, RW())[0]).split())
    assert "Object-Oriented Programming (OOP)" in out and "Object-GraphQL" not in out and "Object-System" not in out, out
    assert "GraphQL" in out and "System Integrations" in out and "Terraform" in out
    assert "Scrum.," not in out and "Agile/Scrum. Experience" in out, out  # the full stop stays only at the end
