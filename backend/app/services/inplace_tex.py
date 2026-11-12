"""Tailoring for LaTeX resumes: edit the .tex source itself, then compile it with pdflatex.

The result is a real LaTeX document — your template, fonts, spacing and hyphenation — not a patched PDF.

Units found in the source (inside \\begin{document}):
  * bullets — `\\item ...` and item macros such as Jake's `\\resumeItem{...}` in experience / project sections
  * skills lines — rows like `\\textbf{Languages}{: Java, Python}` or `\\textbf{Languages:} Java, Python \\\\`
  * the summary — the text of a Summary / Profile / Objective section

Only text that converts cleanly is editable: plain words, \\textbf, \\emph/\\textit, \\href and the usual escapes.
A line using anything else (icons, macros, math beyond simple symbols) is left exactly as it is.
Each edit replaces only that unit's span of source, so everything else in the file stays byte for byte.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from . import latex
from .inplace_pdf import EDITABLE_SECTIONS, FitError, _section_key, normspace


@dataclass
class TexUnit:
    id: str
    kind: str
    section: str
    heading: str
    start: int  # span of this unit's content in the source
    end: int
    rich: list[tuple[str, bool]] = field(default_factory=list)
    label: str = ""
    chars: int = 0

    @property
    def text(self) -> str:
        return normspace("".join(t for t, _ in self.rich))

    def to_public(self) -> dict:
        return {"id": self.id, "kind": self.kind, "section": self.section, "heading": self.heading,
                "text": self.text, "rich": self.rich, "label": self.label, "lines": None, "page": 0}


# ------------------------------------------------------------------ source helpers

def decode(b: bytes) -> str:
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("latin-1")


def _mask_comments(src: str) -> str:
    """Same length as src, with comments blanked out (so searches never match commented-out code)."""
    out = []
    for line in src.splitlines(keepends=True):
        i, cut = 0, None
        while i < len(line):
            if line[i] == "\\":
                i += 2
                continue
            if line[i] == "%":
                cut = i
                break
            i += 1
        if cut is None:
            out.append(line)
        else:
            nl = "\n" if line.endswith("\n") else ""
            out.append(line[:cut] + " " * (len(line) - cut - len(nl)) + nl)
    return "".join(out)


def _match_brace(s: str, i: int) -> int:
    """s[i] == '{' → index of its matching '}' (or -1)."""
    depth = 0
    j = i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


# ------------------------------------------------------------------ LaTeX <-> rich text

_ESC = {"%": "%", "&": "&", "$": "$", "#": "#", "_": "_", "{": "{", "}": "}", " ": " ", ",": " ", ";": " ", "/": "",
        "-": "", "@": ""}
_TEXT_MACROS = {"textit", "emph", "textsl", "underline", "texttt", "textrm", "textsf", "textnormal", "uline", "mbox", "text"}
_SYMBOL_MACROS = {"textbar": "|", "textasciitilde": "~", "textbullet": "•", "textendash": "–", "textemdash": "—",
                  "textbackslash": "\\", "textless": "<", "textgreater": ">", "LaTeX": "LaTeX", "TeX": "TeX",
                  "ldots": "…", "dots": "…", "textquoteright": "’", "textquoteleft": "‘", "textregistered": "®",
                  "texttrademark": "™", "textcopyright": "©", "textdegree": "°"}
_MATH = {r"\sim": "~", r"\%": "%", "|": "|", r"\times": "×", r"\approx": "≈", r"\geq": "≥", r"\ge": "≥", r"\leq": "≤",
         r"\le": "≤", r"\rightarrow": "→", r"\to": "→", r"\cdot": "·", r"\pm": "±", r"\bullet": "•", "+": "+", "-": "−",
         ">": ">", "<": "<", r"\sim\!": "~"}


def tex_to_rich(s: str, bold: bool = False) -> Optional[list[tuple[str, bool]]]:
    """LaTeX snippet → [(text, bold)], or None when it uses something we can't safely re-create."""
    out: list[tuple[str, bool]] = []

    def add(t: str, b: bool):
        if t:
            if out and out[-1][1] == b:
                out[-1] = (out[-1][0] + t, b)
            else:
                out.append((t, b))

    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            if i + 1 < len(s) and s[i + 1] in _ESC:
                add(_ESC[s[i + 1]], bold)
                i += 2
                continue
            if s.startswith("\\\\", i):
                return None  # a forced line break inside the text: leave this line alone
            m = re.match(r"\\([A-Za-z]+)\*?\s*", s[i:])
            if not m:
                return None
            name = m.group(1)
            j = i + m.end()
            if name in ("textbf", "bfseries") and name == "textbf":
                if j >= len(s) or s[j] != "{":
                    return None
                k = _match_brace(s, j)
                inner = tex_to_rich(s[j + 1:k], True)
                if inner is None or k < 0:
                    return None
                for t, b in inner:
                    add(t, b)
                i = k + 1
                continue
            if name in _TEXT_MACROS:
                if j >= len(s) or s[j] != "{":
                    return None
                k = _match_brace(s, j)
                inner = tex_to_rich(s[j + 1:k], bold) if k > 0 else None
                if inner is None:
                    return None
                for t, b in inner:
                    add(t, b)
                i = k + 1
                continue
            if name == "href":
                if j >= len(s) or s[j] != "{":
                    return None
                k1 = _match_brace(s, j)
                if k1 < 0 or k1 + 1 >= len(s) or s[k1 + 1] != "{":
                    return None
                k2 = _match_brace(s, k1 + 1)
                inner = tex_to_rich(s[k1 + 2:k2], bold) if k2 > 0 else None
                if inner is None:
                    return None
                for t, b in inner:
                    add(t, b)
                i = k2 + 1
                continue
            if name in _SYMBOL_MACROS:
                add(_SYMBOL_MACROS[name], bold)
                i = j
                if s.startswith("{}", i):
                    i += 2
                continue
            return None  # \faGithub, \vspace, \small, custom macros ...
        if c == "$":
            k = s.find("$", i + 1)
            if k < 0:
                return None
            math = s[i + 1:k].strip()
            if math.replace(" ", "") in _MATH or math in _MATH:
                add(_MATH.get(math, _MATH.get(math.replace(" ", ""), "")), bold)
            elif re.fullmatch(r"[0-9.,+\-]+", math):
                add(math, bold)
            else:
                return None
            i = k + 1
            continue
        if c in "{}":
            i += 1
            continue
        if c == "~":
            add(" ", bold)
            i += 1
            continue
        if s.startswith("---", i):
            add("—", bold)
            i += 3
            continue
        if s.startswith("--", i):
            add("–", bold)
            i += 2
            continue
        if s.startswith("``", i):
            add("“", bold)
            i += 2
            continue
        if s.startswith("''", i):
            add("”", bold)
            i += 2
            continue
        if c in "^&#_":
            return None
        add(c, bold)
        i += 1
    # collapse whitespace like LaTeX does
    res = []
    for t, b in out:
        t = re.sub(r"\s+", " ", t)
        if t:
            res.append((t, b))
    if res:
        res[0] = (res[0][0].lstrip(), res[0][1])
        res[-1] = (res[-1][0].rstrip(), res[-1][1])
    return [r for r in res if r[0]]


_TO_TEX = [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"),
           ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}"),
           ("—", "---"), ("–", "--"), ("“", "``"), ("”", "''"), ("’", "'"), ("‘", "`"), ("•", r"\textbullet{}"),
           ("→", r"$\rightarrow$"), ("≥", r"$\geq$"), ("≤", r"$\leq$"), ("×", r"$\times$"), ("≈", r"$\approx$"),
           ("·", r"$\cdot$"), ("±", r"$\pm$"), ("−", "-"), ("…", r"\ldots{}"), ("<", r"\textless{}"), (">", r"\textgreater{}"),
           ("|", r"\textbar{}")]


def escape(t: str) -> str:
    out = []
    for ch in t:
        for a, b in _TO_TEX:
            if ch == a:
                out.append(b)
                break
        else:
            out.append(ch)
    return "".join(out)


def rich_to_tex(runs: list[tuple[str, bool]]) -> str:
    merged: list[tuple[str, bool]] = []
    for t, b in runs:
        if merged and merged[-1][1] == b:
            merged[-1] = (merged[-1][0] + t, b)
        elif t:
            merged.append((t, b))
    parts = []
    for t, b in merged:
        if b and t.strip():
            lead = t[: len(t) - len(t.lstrip())]
            trail = t[len(t.rstrip()):]
            parts.append(escape(lead) + r"\textbf{" + escape(t.strip()) + "}" + escape(trail))
        else:
            parts.append(escape(t))
    return "".join(parts)


# ------------------------------------------------------------------ finding units

_SECTION = re.compile(r"\\(?!sub)([A-Za-z]*section|[A-Za-z]*Section)\*?\s*(?:\[[^\]]*\])?\s*\{")
_ANY_MACRO = re.compile(r"\\([A-Za-z]+)\*?\s*\{")
_NOT_HEADING = {"textbf", "textit", "emph", "underline", "href", "url", "textsc", "item", "resumeItem", "begin", "end",
                "vspace", "hspace", "small", "large", "Large", "LARGE", "huge", "textcolor", "color", "mbox", "text"}
_ITEM = re.compile(r"\\item\b\s*(?:\[[^\]]*\])?")
_ITEM_MACRO = re.compile(r"\\(?!item\b)([A-Za-z]*[Ii]tem)\s*\{")  # \resumeItem{...}, \cvitem{...}
_STOP = re.compile(r"\\item\b|\\end\s*\{|\\begin\s*\{|\\[A-Za-z]*(?:ListEnd|ListStart|Heading|heading)\b|\\(?:sub)*section\b")
_LEAD = re.compile(r"^(?:\s|\\(?:small|footnotesize|normalsize|scriptsize|noindent|par)\b\s*|\\[vh]space\*?\{[^{}]*\}\s*)+")
_TRAIL = re.compile(r"(?:\s|\\\\(?:\[[^\]]*\])?|\\newline\b|\\par\b|\\[vh]space\*?\{[^{}]*\})+$")


def _trim(src: str, a: int, b: int) -> tuple[int, int]:
    seg = src[a:b]
    m = _LEAD.match(seg)
    if m:
        a += m.end()
        seg = src[a:b]
    m = _TRAIL.search(seg)
    if m:
        b = a + m.start()
    return a, b


def _unwrap(src: str, a: int, b: int) -> tuple[int, int]:
    """Strip one wrapper group around the whole span: {\\small ...} or \\small{...}."""
    for _ in range(3):
        a, b = _trim(src, a, b)
        seg = src[a:b]
        m = re.match(r"\\(?:small|footnotesize|normalsize)\s*\{", seg)
        if m and _match_brace(src, a + m.end() - 1) == b - 1:
            a, b = a + m.end(), b - 1
            continue
        if seg.startswith("{") and _match_brace(src, a) == b - 1:
            a, b = a + 1, b - 1
            continue
        break
    return _trim(src, a, b)


def _sections(clean: str, body_a: int, body_b: int) -> list[tuple[str, str, int, int]]:
    """[(section key, heading, start of body, end of body)]"""
    found = []
    matches = list(_SECTION.finditer(clean, body_a, body_b))
    if not matches:
        # custom heading macros (\sect{Experience}, \cvsection{...}): any macro used for 2+ known section titles
        by_name: dict[str, list] = {}
        for m in _ANY_MACRO.finditer(clean, body_a, body_b):
            if m.group(1) in _NOT_HEADING:
                continue
            k = _match_brace(clean, m.end() - 1)
            arg = clean[m.end():k] if k > 0 else ""
            if 0 < len(arg) <= 48 and _section_key(re.sub(r"\\[A-Za-z]+|[{}]", "", arg)):
                by_name.setdefault(m.group(1), []).append(m)
        best = max(by_name.values(), key=len, default=[])
        matches = best if len(best) >= 2 else []
    for m in matches:
        k = _match_brace(clean, m.end() - 1)
        if k < 0:
            continue
        rich = tex_to_rich(clean[m.end():k]) or [(re.sub(r"\\[A-Za-z]+|[{}]", "", clean[m.end():k]), False)]
        title = normspace("".join(t for t, _ in rich))
        found.append((title, m.start(), k + 1))
    out = []
    for i, (title, s0, s1) in enumerate(found):
        end = found[i + 1][1] if i + 1 < len(found) else body_b
        out.append((_section_key(title) or "other", title, s1, end))
    return out


def analyze(data: bytes) -> dict:
    files, main = latex.load_project(data)
    src = decode(files[main])
    clean = _mask_comments(src)
    a = clean.find("\\begin{document}")
    b = clean.rfind("\\end{document}")
    if a < 0:
        return {"units": [], "main": main}
    body_a, body_b = a + len("\\begin{document}"), (b if b > a else len(clean))
    units: list[TexUnit] = []
    taken: list[tuple[int, int]] = []

    def add(kind, sec, heading, s, e, label=""):
        s, e = _unwrap(clean, s, e) if kind == "paragraph" else _trim(clean, s, e)
        if e - s < 2 or any(not (e <= x or s >= y) for x, y in taken):
            return
        rich = tex_to_rich(clean[s:e])
        if not rich or len("".join(t for t, _ in rich).strip()) < 3:
            return
        if kind == "skill_line" and not label:
            first = rich[0][0].strip()
            if rich[0][1] and len(rich) > 1 and rich[1][0].lstrip().startswith(":"):
                label = first.rstrip(":") + ":"
            elif rich[0][1] and first.endswith(":"):
                label = first
            elif ":" in "".join(t for t, _ in rich)[:40]:
                label = "".join(t for t, _ in rich).split(":", 1)[0].strip() + ":"
        taken.append((s, e))
        units.append(TexUnit(id=f"u{len(units)}", kind=kind, section=sec, heading=heading, start=s, end=e, rich=rich,
                             label=label, chars=len("".join(t for t, _ in rich))))

    for sec, heading, s0, s1 in _sections(clean, body_a, body_b):
        if sec == "skills":
            for m in re.finditer(r"\\textbf\s*\{", clean[s0:s1]):
                start = s0 + m.start()
                k = _match_brace(clean, s0 + m.end() - 1)
                if k < 0:
                    continue
                j, depth = k + 1, 0
                while j < s1:  # the row ends at \\, a closing group, a blank line, or the next row/item
                    if clean.startswith("\\\\", j) and depth == 0:
                        break
                    ch = clean[j]
                    if ch == "\\":
                        if _STOP.match(clean, j) or (depth == 0 and clean.startswith("\\textbf", j)):
                            break
                        j += 2
                        continue
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth < 0:
                            break
                    elif ch == "\n" and depth == 0 and (clean[j + 1:j + 200].lstrip().startswith(("\\textbf", "\\item", "\\end"))
                                                        or re.match(r"\n\s*\n", clean[j:j + 50])):
                        break
                    j += 1
                add("skill_line", sec, heading, start, j)
            continue
        if sec == "summary":
            seg = clean[s0:s1]
            if "\\item" not in seg and "\\begin{itemize}" not in seg:
                add("paragraph", sec, heading, s0, s1)
                continue
        if sec not in EDITABLE_SECTIONS and sec != "summary":
            continue
        for m in _ITEM_MACRO.finditer(clean, s0, s1):
            name = m.group(1).lower()
            if name.endswith(("liststart", "listend")):
                continue
            k = _match_brace(clean, m.end() - 1)
            if k < 0:
                continue
            last_a, last_b = m.end(), k
            # older templates: \resumeItem{Title}{Description} — edit the description
            if k + 1 < s1 and clean[k + 1:k + 2] == "{":
                k2 = _match_brace(clean, k + 1)
                if k2 > 0:
                    last_a, last_b = k + 2, k2
            add("bullet", sec, heading, last_a, last_b)
        for m in _ITEM.finditer(clean, s0, s1):
            st = m.end()
            stop = _STOP.search(clean, st, s1)
            end = stop.start() if stop else s1
            # inside a group opened before the \item (e.g. \item{ ... }): end at the group's close
            seg = clean[st:end]
            depth = 0
            for idx, ch in enumerate(seg):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth < 0:
                        end = st + idx
                        break
            add("bullet", sec, heading, st, end)
    units.sort(key=lambda u: u.start)
    for i, u in enumerate(units):
        u.id = f"u{i}"
    return {"units": units, "main": main}


# ------------------------------------------------------------------ rendering

def _pages(pdf: bytes) -> int:
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as d:
        return d.page_count


def _build(data: bytes, units: list[TexUnit], edits: dict[str, list[tuple[str, bool]]],
           skill_additions: dict[str, list[str]]) -> tuple[dict[str, bytes], str]:
    files, main = latex.load_project(data)
    src = decode(files[main])
    by_id = {u.id: u for u in units}
    repl: list[tuple[int, int, str]] = []
    for uid, runs in edits.items():
        u = by_id.get(uid)
        if u is not None:
            repl.append((u.start, u.end, rich_to_tex(runs)))
    for uid, items in skill_additions.items():
        u = by_id.get(uid)
        if u is not None and items and uid not in edits:
            joiner = "" if u.text.rstrip().endswith((",", ":")) else ","
            repl.append((u.end, u.end, escape(joiner + " " + ", ".join(items))))
    for s, e, t in sorted(repl, key=lambda r: (r[0], r[1]), reverse=True):
        src = src[:s] + t + src[e:]
    files = dict(files)
    files[main] = src.encode("utf-8")
    return files, main


def render(data: bytes, units: list[TexUnit], edits: dict[str, list[tuple[str, bool]]],
           skill_additions: dict[str, list[str]]) -> tuple[bytes, dict[str, list[str]]]:
    """Compile the edited source. Returns (PDF bytes, {unit id: [warnings]}).

    If the edits push the resume onto an extra page, the edits that grew the text most are undone one at a
    time (added skills first) until it fits again; each undone line gets a warning."""
    warnings: dict[str, list[str]] = {uid: [] for uid in edits}
    try:
        base_pages = _pages(latex.compile_source(data))
    except latex.LatexError as e:
        raise FitError(f"latex: your LaTeX resume doesn't compile ({e}).")
    edits, adds = dict(edits), {k: list(v) for k, v in skill_additions.items() if v}
    by_id = {u.id: u for u in units}
    for _ in range(len(edits) + len(adds) + 1):
        files, main = _build(data, units, edits, adds)
        try:
            pdf = latex.compile_pdf(files, main)
        except latex.LatexError as e:
            raise FitError(f"latex: the tailored LaTeX doesn't compile ({e}).")
        if _pages(pdf) <= base_pages:
            return pdf, warnings
        if adds:
            uid = max(adds, key=lambda k: len(", ".join(adds[k])))
            adds.pop(uid)
            warnings.setdefault(uid, []).append("Added skills were left out: they pushed the resume onto another page.")
            continue
        if not edits:
            break
        grow = lambda k: len(rich_to_tex(edits[k])) - (by_id[k].end - by_id[k].start) if k in by_id else 0
        uid = max(edits, key=grow)
        edits.pop(uid)
        warnings.setdefault(uid, []).append("Kept your original wording: the new text pushed the resume onto another page.")
    raise FitError("latex: the tailored resume doesn't fit on the original number of pages.")


def full_text(data: bytes) -> str:
    from . import inplace_pdf

    pdf = data if data[:5] == b"%PDF-" else latex.compile_source(data)
    return inplace_pdf.full_text(pdf)


def to_pdf(data: bytes) -> bytes:
    return data if data[:5] == b"%PDF-" else latex.compile_source(data)
