"""LaTeX resumes: edit the .tex source and compile it with pdflatex (no PDF patching)."""
import io
import shutil
import zipfile
from pathlib import Path

import pymupdf
import pytest

from app.services import inplace_tex as T
from app.services import latex

FIX = Path(__file__).parent / "fixtures"
SIMPLE = (FIX / "latex_times_resume.tex").read_bytes()
JAKE = (FIX / "latex_jake_style_resume.tex").read_bytes()
needs_tex = pytest.mark.skipif(not latex.available(), reason="pdflatex not installed")


def units(data):
    return {u.id: u for u in T.analyze(data)["units"]}


def test_finds_summary_bullets_and_skills_in_a_custom_template():
    us = list(units(JAKE).values())
    kinds = [(u.kind, u.text[:30]) for u in us]
    assert kinds[0] == ("paragraph", "Data engineer with 4 years of ")
    assert [u.text[:20] for u in us if u.kind == "bullet"] == ["Built Airflow pipeli", "Cut warehouse cost b", "Mentored two analyst"]
    skills = [u for u in us if u.kind == "skill_line"]
    assert [(u.label, u.text) for u in skills] == [("Languages:", "Languages: Python, SQL, Bash"),
                                                  ("Tools:", "Tools: Airflow, dbt, BigQuery, Docker, Git")]
    assert ("Airflow", True) in us[1].rich  # bold kept
    assert not any("commented out" in u.text for u in us)  # comments are never units


def test_custom_heading_macros_are_sections():
    us = list(units(SIMPLE).values())
    assert [u.kind for u in us] == ["paragraph", "skill_line", "skill_line", "skill_line", "bullet", "bullet", "bullet"]


def test_text_conversion_round_trip():
    rich = T.tex_to_rich(r"Cut cost by 25\% for R\&D --- \textbf{BigQuery} \& dbt ``fast'' $\sim$3x")
    assert rich == [("Cut cost by 25% for R&D — ", False), ("BigQuery", True), (" & dbt “fast” ~3x", False)]
    tex = T.rich_to_tex([("50% of R&D #1 under_score — ", False), ("C++", True), (" ~ {x} → done", False)])
    assert tex == r"50\% of R\&D \#1 under\_score --- \textbf{C++} \textasciitilde{} \{x\} $\rightarrow$ done"
    assert T.tex_to_rich(r"Built \faGithub\ tools") is None  # unknown macros: line left alone
    assert T.tex_to_rich(r"Line one \\ line two") is None


def test_edits_change_only_their_spans():
    us = units(JAKE)
    files, main = T._build(JAKE, list(us.values()), {"u2": [("Reduced cost by 25%", False)]}, {"u5": ["Kafka"]})
    new = files[main].decode()
    old = JAKE.decode()
    assert r"\resumeItem{Reduced cost by 25\%}" in new
    assert r"\textbf{Tools}{: Airflow, dbt, BigQuery, Docker, Git}, Kafka" in new
    assert new.replace(r"Reduced cost by 25\%", "").replace(", Kafka", "") == \
        old.replace(old[us["u2"].start:us["u2"].end], "")  # everything else byte for byte


@needs_tex
def test_render_compiles_edits_into_a_real_pdf():
    us = units(JAKE)
    pdf, warnings = T.render(JAKE, list(us.values()),
                             {"u0": [("Data engineer with 4 years building ", False), ("Python", True), (" pipelines on GCP & dbt.", False)]},
                             {"u5": ["Kafka", "Spark"]})
    text = pymupdf.open(stream=pdf)[0].get_text()
    assert "Data engineer with 4 years building Python pipelines on GCP & dbt." in " ".join(text.split())
    assert "Docker, Git, Kafka, Spark" in text
    assert warnings == {"u0": []}


@needs_tex
def test_an_edit_that_adds_a_page_is_undone_with_a_warning():
    us = units(JAKE)
    pdf, warnings = T.render(JAKE, list(us.values()), {"u1": [("Built pipelines " * 400, False)]}, {})
    assert pymupdf.open(stream=pdf).page_count == 1
    assert "another page" in warnings["u1"][0]


@needs_tex
def test_untrusted_source_cannot_read_server_files():
    evil = SIMPLE.replace(b"\\begin{document}", b"\\input{/etc/passwd}\n\\begin{document}")
    with pytest.raises(latex.LatexError, match="not found"):
        latex.compile_source(evil)
    marker = Path("/tmp/jobpilot-shell-escape-test")
    marker.unlink(missing_ok=True)
    latex.compile_source(SIMPLE.replace(b"\\begin{document}",
                                        b"\\immediate\\write18{touch /tmp/jobpilot-shell-escape-test}\n\\begin{document}"))
    assert not marker.exists()  # shell escape is off: the command is ignored, never run


def test_overleaf_zip_project_finds_the_main_file():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("My Resume/resume.tex", JAKE)
        z.writestr("My Resume/notes.tex", b"just notes")
        z.writestr("../evil.tex", b"x")
    files, main = latex.load_project(buf.getvalue())
    assert main == "resume.tex" and "notes.tex" in files and not any(".." in f for f in files)


@needs_tex
def test_upload_tailor_and_download_a_latex_resume(client):
    from .conftest import make_user, setup_profile
    from .test_api import _mock_jobs

    h, _ = make_user(client)
    setup_profile(client, h)
    r = client.post("/api/resumes", headers=h, files={"file": ("resume.tex", JAKE, "application/x-tex")})
    assert r.status_code == 200, r.text
    assert r.json()["resume"]["mime_type"] == "tex" and "Airflow" in r.json()["resume"]["text"]
    rid = r.json()["resume"]["id"]
    assert client.post(f"/api/resumes/{rid}/primary", headers=h).status_code == 200
    assert client.get(f"/api/resumes/{rid}/preview.png", headers=h).headers["content-type"] == "image/png"
    job = _mock_jobs(client, h)[0]
    d = client.post(f"/api/jobs/{job['id']}/resume/tailor", headers=h)
    assert d.status_code == 200, d.text
    doc = d.json()
    assert doc["content"]["file_kind"] == "tex" and doc["content"]["format"] == "inplace"
    pdf = client.get(f"/api/documents/{doc['id']}/download?format=pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    assert client.get(f"/api/documents/{doc['id']}/preview.png", headers=h).status_code == 200


def test_a_tex_file_without_a_document_is_refused(client):
    from .conftest import make_user

    h, _ = make_user(client)
    r = client.post("/api/resumes", headers=h, files={"file": ("part.tex", b"\\section{Skills} Python", "application/x-tex")})
    assert r.status_code == 400 and "documentclass" in r.json()["detail"]
