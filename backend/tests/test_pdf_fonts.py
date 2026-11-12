"""Tailored PDFs must use fonts every reader can decode.

Regression: rewritten lines of LaTeX resumes (Type 1 subset fonts) were re-embedded as CIDFontType0 with a Type 1
font program. Chrome and MuPDF guessed right, but Ghostscript (and other strict readers / ATS parsers) showed the
lines as garbage like "$ +  ) 5 @ .@". Fixture: tests/fixtures/latex_times_resume.tex built with pdflatex + times.
"""
import shutil
import subprocess
from pathlib import Path

import pymupdf
import pytest

from app.services import inplace_pdf as P

FIXTURE = Path(__file__).parent / "fixtures" / "latex_times_resume.pdf"

SUMMARY = [("Backend engineer with 3 years building ", False), ("Java", True),
           (" and Python services on AWS — REST APIs, SQL and “well-tested” code.", False)]
BULLET = [("Designed ", False), ("REST APIs in Java and Spring", True),
          (" for an order service handling 2M requests per day, reducing latency by 35%.", False)]


def _render():
    data = FIXTURE.read_bytes()
    units = {u.text[:12]: u for u in P.analyze(data)["units"]}
    summ, bullet = units["Software eng"], units["Built REST A"]
    out, _ = P.render(data, list(units.values()), {summ.id: SUMMARY, bullet.id: BULLET}, {})
    return data, out


def test_fixture_really_has_type1_subset_fonts():
    fonts = pymupdf.open(FIXTURE)[0].get_fonts(full=True)
    assert any(f[1] in ("pfa", "pfb") and "+" in f[3] for f in fonts)


def test_rewritten_lines_use_valid_fonts():
    data, out = _render()
    assert P.font_problems(data) == []
    assert P.font_problems(out) == []
    text = pymupdf.open(stream=out)[0].get_text()
    assert "Backend engineer with 3 years building Java" in text and "Designed REST APIs in Java and Spring" in text


@pytest.mark.skipif(not shutil.which("gs"), reason="Ghostscript not installed")
def test_strict_reader_decodes_the_rewritten_lines(tmp_path):
    _, out = _render()
    f = tmp_path / "out.pdf"
    f.write_bytes(out)
    txt = subprocess.run(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=txtwrite", "-sOutputFile=-", str(f)],
                         capture_output=True, text=True, timeout=60).stdout
    assert "Backend engineer with 3 years building Java" in txt
    assert "Designed REST APIs in Java and Spring" in txt
    assert "$ +" not in txt


def test_the_old_behaviour_is_caught_before_reaching_the_user(monkeypatch):
    # re-embedding the resume's own Type 1 font is exactly what produced the garbage: the guard must refuse it
    monkeypatch.setattr(P, "REUSABLE_FONT_TYPES", ("ttf", "otf", "pfa", "pfb"))
    with pytest.raises(P.FitError, match="garbled"):
        _render()
