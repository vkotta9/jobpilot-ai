"""Format-preserving resume editing for PDF files.

Instead of regenerating a resume, this module edits the user's own PDF:

* `analyze(pdf)` finds editable *units* — the summary paragraph, each bullet
  point and each skills line — with their exact geometry, fonts and bold runs.
* `render(pdf, edits, skill_additions)` removes only the text of the edited
  units and re-typesets the new wording in the same box, with the same font
  (the PDF's embedded font when it has every glyph, otherwise the matching
  standard family), size, colour, bold runs, line pitch and justification.
  Skills are appended to the end of existing skills lines.

Everything else on the page — name, contact details, links, headings, rules,
dates, other sections — is never touched.
"""
from __future__ import annotations

import io
import re
import statistics
from dataclasses import dataclass, field
from typing import Optional

import pymupdf

BULLET_CHARS = set("•●▪◦‣∙·*–-")
SECTION_ALIASES = {
    "summary": ("summary", "professional summary", "profile", "about", "objective", "career summary", "about me",
                "professional profile", "career objective"),
    "experience": ("experience", "work experience", "professional experience", "employment", "employment history",
                   "work history", "career history", "relevant experience"),
    "projects": ("projects", "academic projects", "personal projects", "selected projects", "key projects"),
    "skills": ("skills", "technical skills", "core skills", "core competencies", "competencies", "skills & tools",
               "technologies", "tools", "technical proficiencies", "skills and tools", "key skills"),
    "education": ("education", "academic background"),
    "publications": ("publications", "research publication", "research publications", "publication", "research"),
    "achievements": ("achievements", "awards", "honors", "awards & achievements", "certifications", "certificates",
                     "leadership", "activities", "extracurricular activities", "volunteering"),
}
EDITABLE_SECTIONS = {"summary", "experience", "projects", "publications", "other"}


class FitError(ValueError):
    """New text does not fit in the space of the original."""


@dataclass
class Span:
    text: str
    font: str
    size: float
    bold: bool
    italic: bool
    color: int
    bbox: tuple
    origin: tuple


@dataclass
class Line:
    page: int
    bbox: tuple
    spans: list[Span]

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    @property
    def baseline(self) -> float:
        return self.spans[0].origin[1]


@dataclass
class Unit:
    id: str
    kind: str  # paragraph | bullet | skill_line
    section: str
    heading: str
    page: int
    lines: list[Line]
    text_x0: float  # where text starts on the first line (after the bullet glyph)
    cont_x0: float  # where continuation lines start
    right: float
    pitch: float
    justified: bool
    size: float
    color: int
    regular_font: str
    bold_font: str
    rich: list[tuple[str, bool]] = field(default_factory=list)  # (text, bold) runs, bullet glyph excluded
    label: str = ""  # skills line label e.g. "Cloud & Tools:"

    @property
    def text(self) -> str:
        return normspace("".join(t for t, _ in self.rich))

    def to_public(self) -> dict:
        return {"id": self.id, "kind": self.kind, "section": self.section, "heading": self.heading,
                "text": self.text, "rich": self.rich, "label": self.label, "lines": len(self.lines),
                "page": self.page}


def normspace(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _canon_font(name: str) -> str:
    return name.split("+", 1)[-1]


def _is_bold(span: dict) -> bool:
    f = span["font"].lower()
    return bool(span["flags"] & 16) or any(k in f for k in ("bold", "medi", "black", "heavy", "semibold", "demi"))


def _is_italic(span: dict) -> bool:
    f = span["font"].lower()
    return bool(span["flags"] & 2) or "ital" in f or "oblique" in f


def _section_key(text: str) -> Optional[str]:
    t = re.sub(r"[^a-z& ]", "", text.lower()).strip()
    for key, aliases in SECTION_ALIASES.items():
        if t in aliases:
            return key
    return None


def _read_lines(doc: pymupdf.Document) -> list[Line]:
    out: list[Line] = []
    for pno, page in enumerate(doc):
        d = page.get_text("dict")
        for b in d["blocks"]:
            for l in b.get("lines", []):
                spans = [Span(s["text"], s["font"], round(s["size"], 2), _is_bold(s), _is_italic(s), s["color"],
                              tuple(s["bbox"]), tuple(s["origin"])) for s in l["spans"] if s["text"]]
                if spans and normspace("".join(s.text for s in spans)):
                    out.append(Line(pno, tuple(l["bbox"]), spans))
    # reading order: page, then baseline, then x
    out.sort(key=lambda ln: (ln.page, round(ln.baseline, 0), ln.bbox[0]))
    return _merge_same_baseline(out)


def _merge_same_baseline(lines: list[Line]) -> list[Line]:
    """Join fragments that sit on the same baseline and touch (PDF producers split lines)."""
    merged: list[Line] = []
    for ln in lines:
        prev = merged[-1] if merged else None
        if prev and prev.page == ln.page and abs(prev.baseline - ln.baseline) < 1.0 and 0 <= ln.bbox[0] - prev.bbox[2] < 8:
            prev.spans.extend(ln.spans)
            prev.bbox = (prev.bbox[0], min(prev.bbox[1], ln.bbox[1]), ln.bbox[2], max(prev.bbox[3], ln.bbox[3]))
        else:
            merged.append(ln)
    return merged


def _body_size(lines: list[Line]) -> float:
    weights: dict[float, int] = {}
    for ln in lines:
        for s in ln.spans:
            weights[s.size] = weights.get(s.size, 0) + len(s.text.strip())
    return max(weights, key=weights.get) if weights else 10.0


def _is_heading(ln: Line, body: float) -> bool:
    txt = normspace(ln.text)
    if not txt or len(txt) > 45:
        return False
    big = all(s.size >= body * 1.15 for s in ln.spans if s.text.strip())
    allbold = all(s.bold for s in ln.spans if s.text.strip())
    caps = txt.isupper() and len(txt) > 3
    return big or (_section_key(txt) is not None and (allbold or caps))


def _starts_bullet(ln: Line) -> bool:
    first = ln.text.lstrip()
    return bool(first) and first[0] in BULLET_CHARS and (len(first) == 1 or first[1] in " \t " or first[0] == "•")


def _rich_from_lines(lines: list[Line], skip_bullet: bool) -> list[tuple[str, bool]]:
    runs: list[tuple[str, bool]] = []
    for i, ln in enumerate(lines):
        spans = list(ln.spans)
        if i == 0 and skip_bullet:
            # drop the glyph (and whitespace after it)
            while spans and (not spans[0].text.strip() or spans[0].text.strip()[0] in BULLET_CHARS):
                s = spans.pop(0)
                rest = s.text.strip()[1:] if s.text.strip() and s.text.strip()[0] in BULLET_CHARS else ""
                if rest.strip():
                    spans.insert(0, Span(rest, s.font, s.size, s.bold, s.italic, s.color, s.bbox, s.origin))
                    break
        if i > 0:
            # join with the previous line: hyphenated breaks ("life-" + "cycle") keep the hyphen
            if runs and not runs[-1][0].endswith(("-", "/")):
                runs.append((" ", False))
        for s in spans:
            if runs and runs[-1][1] == s.bold:
                runs[-1] = (runs[-1][0] + s.text, s.bold)
            else:
                runs.append((s.text, s.bold))
    # normalise whitespace inside runs, drop empties
    out: list[tuple[str, bool]] = []
    for t, b in runs:
        t = re.sub(r"\s+", " ", t)
        if not t:
            continue
        if out and out[-1][1] == b:
            out[-1] = (out[-1][0] + t, b)
        else:
            out.append((t, b))
    if out:
        out[0] = (out[0][0].lstrip(), out[0][1])
        out[-1] = (out[-1][0].rstrip(), out[-1][1])
    return [r for r in out if r[0]]


def _first_text_x(ln: Line, skip_bullet: bool) -> float:
    for s in ln.spans:
        t = s.text.strip()
        if not t:
            continue
        if skip_bullet and t[0] in BULLET_CHARS and len(t) == 1:
            continue
        return s.bbox[0]
    return ln.bbox[0]


def _fonts_of(lines: list[Line], body: float) -> tuple[str, str, float, int]:
    reg = [s for ln in lines for s in ln.spans if not s.bold and not s.italic and s.text.strip()]
    bold = [s for ln in lines for s in ln.spans if s.bold and s.text.strip()]
    base = reg or [s for ln in lines for s in ln.spans if s.text.strip()]
    size = statistics.median(s.size for s in base) if base else body
    color = base[0].color if base else 0
    return (base[0].font if base else ""), (bold[0].font if bold else ""), size, color


def analyze(data: bytes) -> dict:
    doc = pymupdf.open(stream=data, filetype="pdf")
    lines = _read_lines(doc)
    body = _body_size(lines)
    right_margin = max((ln.bbox[2] for ln in lines), default=500)
    # typical pitch between consecutive body lines
    gaps = [b.baseline - a.baseline for a, b in zip(lines, lines[1:])
            if a.page == b.page and 0 < b.baseline - a.baseline < body * 1.8]
    doc_pitch = statistics.median(gaps) if gaps else body * 1.2

    units: list[Unit] = []
    section, heading = "header", ""
    i = 0
    seen_heading = False
    para: list[Line] = []

    def flush_para():
        nonlocal para
        if para and section in ("summary",):
            _add_unit(units, "paragraph", section, heading, para, False, right_margin, doc_pitch, body)
        para = []

    while i < len(lines):
        ln = lines[i]
        if _is_heading(ln, body):
            flush_para()
            heading = normspace(ln.text)
            section = _section_key(heading) or "other"
            seen_heading = True
            i += 1
            continue
        if not seen_heading:  # name / contact block — never editable
            i += 1
            continue
        if _starts_bullet(ln):
            flush_para()
            group = [ln]
            text_x = _first_text_x(ln, True)
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if nxt.page != ln.page or _is_heading(nxt, body) or _starts_bullet(nxt):
                    break
                if nxt.baseline - group[-1].baseline > doc_pitch * 1.45:
                    break
                if nxt.bbox[0] < text_x - 3:  # back at the margin => new item (e.g. role header)
                    break
                group.append(nxt)
                j += 1
            if section in EDITABLE_SECTIONS:
                _add_unit(units, "bullet", section, heading, group, True, right_margin, doc_pitch, body)
            elif section == "skills":
                _add_unit(units, "skill_line", section, heading, group[:1], True, right_margin, doc_pitch, body)
            i = j
            continue
        if section == "skills":
            flush_para()
            _add_unit(units, "skill_line", section, heading, [ln], False, right_margin, doc_pitch, body)
            i += 1
            continue
        if section == "summary":
            if para and (ln.baseline - para[-1].baseline > doc_pitch * 1.45 or ln.page != para[-1].page):
                flush_para()
            para.append(ln)
            i += 1
            continue
        i += 1
    flush_para()
    for n, u in enumerate(units):
        u.id = f"u{n}"
    doc.close()
    return {"units": units, "body_size": body, "right": right_margin, "pitch": doc_pitch}


def _add_unit(units: list[Unit], kind: str, section: str, heading: str, group: list[Line], bullet: bool,
              right_margin: float, doc_pitch: float, body: float) -> None:
    rich = _rich_from_lines(group, bullet)
    if not rich:
        return
    reg, bold, size, color = _fonts_of(group, body)
    text_x0 = _first_text_x(group[0], bullet)
    cont_x0 = group[1].bbox[0] if len(group) > 1 else text_x0
    pitch = statistics.median([b.baseline - a.baseline for a, b in zip(group, group[1:])]) if len(group) > 1 else doc_pitch
    justified = any(ln.bbox[2] > right_margin - 2.5 for ln in group[:-1]) if len(group) > 1 else False
    label = ""
    if kind == "skill_line":
        if rich[0][1] and rich[0][0].rstrip().endswith(":"):
            label = rich[0][0].strip()
        elif ":" in rich[0][0][:40]:
            label = rich[0][0].split(":", 1)[0].strip() + ":"
    units.append(Unit(id="", kind=kind, section=section, heading=heading, page=group[0].page, lines=group,
                      text_x0=text_x0, cont_x0=cont_x0, right=right_margin, pitch=pitch, justified=justified,
                      size=size, color=color, regular_font=reg, bold_font=bold or reg, rich=rich, label=label))


# ------------------------------------------------------------------ rendering

_STD = {"serif": ("tiro", "tibo"), "sans": ("helv", "hebo"), "mono": ("cour", "cobo")}


def _family(fontname: str) -> str:
    f = fontname.lower()
    if any(k in f for k in ("mono", "courier", "consol", "menlo", "cmtt")):
        return "mono"
    if any(k in f for k in ("sans", "helvet", "arial", "calibri", "verdana", "roboto", "lato", "open", "segoe",
                             "inter", "source", "montserrat", "nunito", "poppins", "cmss", "lmsans", "carlito")):
        return "sans"
    return "serif"


class _FontKit:
    def __init__(self, doc: pymupdf.Document, page: pymupdf.Page):
        self.doc, self.page = doc, page
        self._embedded: dict[str, Optional[pymupdf.Font]] = {}
        self._by_name = {_canon_font(f[3]): f[0] for f in page.get_fonts(full=True)}

    def embedded(self, name: str) -> Optional[pymupdf.Font]:
        key = _canon_font(name)
        if key not in self._embedded:
            font = None
            xref = self._by_name.get(key)
            if xref:
                try:
                    _, _, _, buf = self.doc.extract_font(xref)
                    if buf:
                        font = pymupdf.Font(fontbuffer=buf)
                except Exception:
                    font = None
            self._embedded[key] = font
        return self._embedded[key]

    def pick(self, unit: Unit, text_runs: list[tuple[str, bool]]) -> tuple[pymupdf.Font, pymupdf.Font]:
        reg = self.embedded(unit.regular_font)
        bold = self.embedded(unit.bold_font)
        need_reg = {c for t, b in text_runs if not b for c in t if not c.isspace()}
        need_bold = {c for t, b in text_runs if b for c in t if not c.isspace()}
        if reg and bold and all(reg.has_glyph(ord(c)) for c in need_reg) and all(bold.has_glyph(ord(c)) for c in need_bold):
            return reg, bold
        r, b = _STD[_family(unit.regular_font)]
        return pymupdf.Font(r), pymupdf.Font(b)


def _words(runs: list[tuple[str, bool]]) -> list[list[tuple[str, bool]]]:
    """Split runs into words; a word may contain several (text, bold) pieces."""
    words: list[list[tuple[str, bool]]] = []
    cur: list[tuple[str, bool]] = []
    for text, bold in runs:
        for piece in re.split(r"(\s+)", text):
            if not piece:
                continue
            if piece.isspace():
                if cur:
                    words.append(cur)
                    cur = []
            else:
                cur.append((piece, bold))
    if cur:
        words.append(cur)
    return words


def _layout(unit: Unit, runs: list[tuple[str, bool]], reg: pymupdf.Font, bold: pymupdf.Font, size: float):
    words = _words(runs)
    width = lambda w: sum((bold if b else reg).text_length(t, size) for t, b in w)
    space = reg.text_length(" ", size)
    lines: list[list] = []
    cur: list = []
    cur_w = 0.0
    for w in words:
        avail = unit.right - (unit.text_x0 if not lines else unit.cont_x0)
        ww = width(w)
        if cur and cur_w + space + ww > avail + 0.5:
            lines.append(cur)
            cur, cur_w = [w], ww
        else:
            cur_w = cur_w + (space if cur else 0) + ww
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines, width, space


MIN_SCALE = 0.92  # the most a rewritten line's font may shrink to keep the layout (also used by _write_unit)


def fits(data_or_doc, unit: Unit, runs: list[tuple[str, bool]], allow_shrink: bool = False) -> dict:
    doc = data_or_doc if isinstance(data_or_doc, pymupdf.Document) else pymupdf.open(stream=data_or_doc, filetype="pdf")
    kit = _FontKit(doc, doc[unit.page])
    reg, bold = kit.pick(unit, runs)
    size = unit.size
    lines, _, _ = _layout(unit, runs, reg, bold, size)
    while allow_shrink and len(lines) > len(unit.lines) and size > unit.size * MIN_SCALE:
        size = round(size - 0.1, 2)
        lines, _, _ = _layout(unit, runs, reg, bold, size)
    return {"needed": len(lines), "available": len(unit.lines), "fits": len(lines) <= len(unit.lines), "size": size}


def _write_unit(doc: pymupdf.Document, page: pymupdf.Page, unit: Unit, runs: list[tuple[str, bool]]) -> list[str]:
    warnings: list[str] = []
    kit = _FontKit(doc, page)
    reg, bold = kit.pick(unit, runs)
    size = unit.size
    lines, width, space = _layout(unit, runs, reg, bold, size)
    while len(lines) > len(unit.lines) and size > unit.size * MIN_SCALE:
        size = round(size - 0.1, 2)
        lines, width, space = _layout(unit, runs, reg, bold, size)
    if len(lines) > len(unit.lines):
        raise FitError(f"needs {len(lines)} lines but only {len(unit.lines)} are available")
    if size < unit.size:
        warnings.append(f"slightly reduced font size ({unit.size:g}→{size:g}pt) to keep the layout")
    color = pymupdf.sRGB_to_pdf(unit.color)
    tw = pymupdf.TextWriter(page.rect, color=color)
    for li, words in enumerate(lines):
        x0 = unit.text_x0 if li == 0 else unit.cont_x0
        y = unit.lines[li].baseline
        avail = unit.right - x0
        natural = sum(width(w) for w in words) + space * (len(words) - 1)
        gap = space
        last = li == len(lines) - 1
        if unit.justified and not last and len(words) > 1:
            gap = space + (avail - natural) / (len(words) - 1)
            gap = min(gap, space * 3)  # never produce rivers
        x = x0
        for w in words:
            for t, b in w:
                f = bold if b else reg
                tw.append((x, y), t, font=f, fontsize=size)
                x += f.text_length(t, size)
            x += gap
    tw.write_text(page)
    return warnings


def _redact_unit(page: pymupdf.Page, unit: Unit, from_x: Optional[float] = None) -> None:
    for li, ln in enumerate(unit.lines):
        x0, y0, x1, y1 = ln.bbox
        h = y1 - y0
        start = (unit.text_x0 if li == 0 else x0) - 0.3
        if from_x is not None:
            start = from_x
        rect = pymupdf.Rect(start, y0 + h * 0.18, max(x1, unit.right) + 1, y1 - h * 0.18)
        page.add_redact_annot(rect, fill=False)


def render(data: bytes, units: list[Unit], edits: dict[str, list[tuple[str, bool]]],
           skill_additions: dict[str, list[str]]) -> tuple[bytes, dict[str, list[str]]]:
    """Return (new_pdf_bytes, {unit_id: [warnings]}). Raises FitError with the unit id prefix."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    by_id = {u.id: u for u in units}
    warnings: dict[str, list[str]] = {}
    # pass 1: redactions per page (one apply per page)
    pages_touched: dict[int, list[Unit]] = {}
    edits = dict(edits)
    for uid, items in skill_additions.items():
        u = by_id.get(uid)
        if u is not None and items and uid not in edits:
            last = u.rich[-1]
            joiner = "" if last[0].rstrip().endswith((",", ":")) else ","
            edits[uid] = list(u.rich) + [(joiner + " " + ", ".join(items), False)]
    skill_additions = {}
    for uid in list(edits):
        u = by_id.get(uid)
        if u is None:
            continue
        pages_touched.setdefault(u.page, [])
        if uid in edits and u not in pages_touched[u.page]:
            pages_touched[u.page].append(u)
    for pno, us in pages_touched.items():
        page = doc[pno]
        for u in us:
            _redact_unit(page, u)
        if us:
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                                  graphics=getattr(pymupdf, "PDF_REDACT_LINE_ART_NONE", 0),
                                  text=getattr(pymupdf, "PDF_REDACT_TEXT_REMOVE", 0))
    # pass 2: write new text
    for uid, runs in edits.items():
        u = by_id[uid]
        try:
            warnings[uid] = _write_unit(doc, doc[u.page], u, runs)
        except FitError as e:
            doc.close()
            if by_id[uid].kind == "skill_line":
                raise FitError(f"{uid}: no room on the '{by_id[uid].label or 'skills'}' line for the added skills")
            raise FitError(f"{uid}: {e}")
    for uid, items in skill_additions.items():
        u = by_id[uid]
        if not items:
            continue
        page = doc[u.page]
        kit = _FontKit(doc, page)
        add = ", " + ", ".join(items)
        last = u.lines[-1]
        if uid in edits:  # line was rewritten; recompute end
            continue
        reg, _ = kit.pick(u, [(add, False)])
        end_x = max(s.bbox[2] for s in last.spans)
        if end_x + reg.text_length(add, u.size) > u.right + 0.5:
            doc.close()
            raise FitError(f"{uid}: no room on the '{u.label or u.text[:20]}' line for {', '.join(items)}")
        tw = pymupdf.TextWriter(page.rect, color=pymupdf.sRGB_to_pdf(u.color))
        tw.append((end_x, last.baseline), add, font=reg, fontsize=u.size)
        tw.write_text(page)
    out = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return out, warnings


def free_width(unit: Unit, data: bytes, text: str) -> float:
    """Remaining width on a skills line if `text` were appended (negative = overflow)."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    kit = _FontKit(doc, doc[unit.page])
    reg, _ = kit.pick(unit, [(text, False)])
    end_x = max(s.bbox[2] for s in unit.lines[-1].spans)
    w = unit.right - (end_x + reg.text_length(text, unit.size))
    doc.close()
    return w


def page_png(data: bytes, page: int = 0, dpi: int = 110) -> bytes:
    doc = pymupdf.open(stream=data, filetype="pdf")
    page = max(0, min(page, doc.page_count - 1))
    png = doc[page].get_pixmap(dpi=dpi).tobytes("png")
    doc.close()
    return png


def page_count(data: bytes) -> int:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return doc.page_count


def full_text(data: bytes) -> str:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return "\n".join(p.get_text("text", sort=True) for p in doc)
