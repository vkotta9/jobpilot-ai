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
