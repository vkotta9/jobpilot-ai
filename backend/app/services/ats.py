"""ATS-style match score: how well a resume's text matches a job description.

Applicant tracking systems rank candidates mostly by keyword overlap with the
posting, plus job title, years of experience and education. There is no single
standard algorithm, so this is a transparent estimate built the same way:

    hard skills & keywords  (default 45)  JD skills/tools/phrases found in the resume
    job title               (default 15)  posting title vs. titles in the resume
    experience              (default 15)  years required vs. years in the resume's dates
    education               (default 15)  degree level / field required vs. resume
    soft skills             (default 10)

Companies shortlist the strongest candidates, not the ones who just clear the bar, so the score measures
you against both the required and the preferred qualifications: preferred skills count almost as much as
required ones, experience is full only at the preferred years (for your degree: "MS + 6 years OR BS + 8
years"), and education is full only at the preferred degree. "C, C++, Java, or Python" lists count once, as
any-of. Matching runs against the actual
resume text (the uploaded file, or the tailored version), never against
anything the candidate hasn't written.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .textutil import SKILL_VOCAB, STOPWORDS, canon_skill, contains_term, find_skills

BUSINESS_VOCAB = [
    "partner management", "partnerships", "account management", "business development", "crm", "b2b", "saas",
    "api integrations", "integrations", "apis", "rest apis", "json", "xml", "webhooks", "sdk", "technical account management",
    "solutions engineering", "program management", "go-to-market", "kpis", "okrs", "contract negotiation",
    "vendor management", "onboarding", "data-driven", "forecasting", "pipeline management", "hubspot", "zendesk",
    "marketplace", "e-commerce", "payments", "fintech", "travel", "hospitality", "pricing", "revenue", "p&l",
    "market research", "competitive analysis", "roadmap", "requirements gathering", "user stories", "process improvement",
    "change management", "risk management", "compliance", "budgeting", "reporting", "dashboards", "sql",
    "microservices", "cloud", "devops", "monitoring", "observability", "incident management", "troubleshooting",
    "automation", "scripting", "data pipelines", "data modeling", "data visualization", "etl", "big data",
    "object-oriented programming", "oop", "data structures", "algorithms", "software development life cycle", "sdlc",
    "code review", "debugging", "performance optimization", "scalability", "high availability", "security",
    "azure devops", "apache camel", "jboss", "splunk", "spring boot", "hibernate", "junit", "selenium", "postman",
    "jenkins", "maven", "gradle", "bitbucket", "confluence", "servicenow", "power automate", "excel", "google analytics",
]
SOFT_SKILLS = [
    "communication", "collaboration", "leadership", "teamwork", "problem solving", "ownership",
    "negotiation", "presentation", "stakeholder management", "cross-functional", "mentoring", "adaptability",
    "attention to detail", "time management", "critical thinking", "customer focus", "relationship building",
    "self-starter", "analytical", "organization", "prioritization", "influence", "accountability", "creativity",
]
DEGREE_LEVELS = [
    (3, r"\b(ph\.?\s?d|doctorate|doctoral)\b"),
    (2, r"\b(master'?s?|m\.?s\.?|m\.?sc|mba|m\.?tech|m\.?eng)\b"),
    (1, r"\b(bachelor'?s?|b\.?s\.?|b\.?a\.?|b\.?sc|b\.?tech|b\.?e\.?|undergraduate degree|4-year degree)\b"),
]
FIELDS = ["computer science", "computer engineering", "software engineering", "information technology",
          "information systems", "electrical engineering", "data science", "statistics", "mathematics",
          "business administration", "economics", "finance", "marketing", "engineering"]

REQ_HDR = re.compile(r"(requirement|qualification|what you('|’)ll need|what you need|must have|you have|you bring|"
                     r"what we('|’)re looking for|who you are|minimum|basic qualifications|skills and experience|"
                     r"about you|your experience)", re.I)
PREF_HDR = re.compile(r"(preferred|nice to have|nice-to-have|bonus|plus|desired|good to have|extra credit)", re.I)
OTHER_HDR = re.compile(r"(benefit|perks|about us|about the company|compensation|salary|equal opportunity|"
                       r"what we offer|why join|our values|eeo)", re.I)

GENERIC_CAPS = set("""The We You Our Your This That About Join Team Company Role Job Position Work Remote Hybrid
Location Benefits Requirements Qualifications Responsibilities Preferred Nice Bonus Plus Who What Why How When Where
Equal Opportunity Employer Inc LLC Ltd Corp January February March April May June July August September October
November December Monday Friday US USA United States America New York San Francisco CA NY TX Senior Junior Lead
Manager Director Engineer Engineering Developer Analyst Associate Intern Full Part Time Must Strong Excellent Experience
Ability Knowledge Understanding Proficiency Familiarity Minimum Years Degree Bachelor Master PhD BS MS BA MBA
EEO Apply Please Note All Any Some Other Help Build Drive Own Lead Partner Partners Global World""".split())


@dataclass
class Keyword:
    term: str
    kind: str  # hard | soft
    weight: float
    required: bool
    count: int
    group: str = ""  # one listed qualification: "any…" = "A, B, or C" (any member meets it); "all…" = examples (partial credit)
    section: str = "general"  # req | pref | general


def _variants(term: str) -> list[str]:
    t = canon_skill(term)
    out = {t}
    if t.endswith("s") and len(t) > 4:
        out.add(t[:-1])
    elif len(t) > 3 and not t.endswith("s") and " " not in t:
        out.add(t + "s")
    if "-" in t:
        out.add(t.replace("-", " "))
        out.add(t.replace("-", ""))
    if " " in t:
        out.add(t.replace(" ", "-"))
    return list(out)


def has_term(text_norm: str, term: str) -> bool:
    return any(contains_term(text_norm, v) for v in _variants(term))


def has_soft(text_norm: str, term: str) -> bool:
    """Soft skills match on word stems: 'collaboration' ~ 'collaborated', 'mentoring' ~ 'mentored'."""
    words = re.findall(r"[a-z]+", term.lower())
    stems = [w[:max(5, len(w) - 4)] if len(w) > 6 else w for w in words]
    return bool(re.search(r"(?<![a-z])" + r"[a-z]*[\s-]+".join(re.escape(st) for st in stems), text_norm))


def _segments(jd: str) -> list[tuple[str, str]]:
    """Split JD into (weight_class, text) chunks: req | pref | other | general."""
    out = []
    cls = "general"
    for raw in jd.splitlines():
        line = raw.strip()
        if not line:
            continue
        short = len(line) < 70 and not line.endswith(".")
        if short and OTHER_HDR.search(line):
            cls = "other"
        elif short and PREF_HDR.search(line):
            cls = "pref"
        elif short and REQ_HDR.search(line):
            cls = "req"
        line_cls = cls
        if cls in ("general", "req") and re.search(r"\b(preferred|nice to have|a plus|is a plus|bonus)\b", line, re.I):
            line_cls = "pref"
        out.append((line_cls, line))
    return out


def _dynamic_terms(line: str, company: str) -> list[str]:
    """Product names / acronyms not in the vocabulary (e.g. 'Salesforce', 'OTA', 'PMS', 'GraphQL')."""
    terms = []
    comp = {w.lower() for w in re.findall(r"[A-Za-z]+", company or "")}
    for m in re.finditer(r"(?<![\w])([A-Z][a-zA-Z0-9+#.]*[A-Z0-9+#][a-zA-Z0-9+#.]*|[A-Z]{2,6}s?)(?![\w])", line):
        tok = m.group(1).rstrip(".")
        if tok in GENERIC_CAPS or tok.lower() in comp or tok.lower() in STOPWORDS or len(tok) < 2:
            continue
        if tok.isupper() and len(tok) > 6:
            continue
        terms.append(tok)
    return terms


LIST_TRIGGER = re.compile(r"\b(?:such as|including(?:,? but not limited to,?)?|e\.g\.,?|for example|like)\s+", re.I)
GENERIC_ITEMS = set("""planning design development management systems system tools tool experience knowledge languages
language production software technologies technology techniques technique methods practices concepts skills areas
things work projects products services solutions platforms frameworks environments etc others other similar related
field fields degree years equivalent ability understanding familiarity proficiency applications application""".split())


def _clean_item(raw: str) -> list[str]:
    """'static analysis (SAST)' -> ['static analysis', 'sast']; drops generic words and filler."""
    out = []
    for acr in re.findall(r"\(([A-Za-z][A-Za-z0-9+#/ .-]{1,20})\)", raw):
        out += [a.strip().lower() for a in re.split(r"[/,]", acr) if 2 <= len(a.strip()) <= 12]
    t = re.sub(r"\([^)]*\)", " ", raw)
    t = t.strip()
    while True:  # 'or other program analysis tools' -> 'program analysis tools'
        t2 = re.sub(r"^(?:and|or|other|the|a|an|any|some|various|etc)\b\s*", "", t, flags=re.I)
        if t2 == t:
            break
        t = t2
    if re.search(r"\b(?:tools?|systems?|techniques?|methods?)$", t, re.I) and raw.strip().lower().startswith(("or other", "and other", "other")):
        return out  # 'other … tools' is filler, not a skill
    t = re.sub(r"\b(?:etc|and so on)\.?$", "", t, flags=re.I).strip(" .;:-")
    words = t.split()
    if not words or len(words) > 4 or len(t) > 40 or re.search(r"\d{2,}|years?\b", t, re.I):
        return out
    low = t.lower()
    if len(words) == 1:
        if low in GENERIC_ITEMS or low in STOPWORDS or (len(low) < 6 and not re.fullmatch(r"[A-Z][A-Z0-9+#]{1,5}s?", t)):
            if low not in SKILL_VOCAB:
                return out
    elif all(w.lower() in GENERIC_ITEMS or w.lower() in STOPWORDS for w in words):
        return out
    return [low] + out


def list_items(line: str) -> tuple[list[str], str]:
    """Items of an enumerated list in a requirement line, and whether it's an any-of ('…, or X') list.

    'Experience with techniques such as taint analysis, fuzzing, or symbolic execution' ->
    (['taint analysis', 'fuzzing', 'symbolic execution'], 'any'); an and-list of examples gives 'all';
    lines without a list give ([], '').
    """
    for sent in re.split(r"(?<=[.;])\s+", line):
        m = LIST_TRIGGER.search(sent)
        body = sent[m.end():] if m else sent
        if body.count(",") < (1 if m else 2):
            continue
        parts = [x for x in re.split(r",\s*|\s*;\s*", body.rstrip(". ")) if x.strip()]
        if not m:  # 'Experience building or working on security scanners, static analysis, …': keep the head noun
            parts[0] = " ".join(parts[0].split()[-2:])
        any_of = bool(re.match(r"\s*or\b", parts[-1], re.I)) or bool(re.search(r",\s*or\s", body))
        items = []
        for part in parts:
            for piece in re.split(r"^or\s+|\s+or\s+", part) if any_of else [part]:
                halves = re.split(r"\s+and\s+", piece)  # 'authentication and authorization' -> both
                for half in (halves if len(halves) == 2 and all(0 < len(x.split()) <= 3 for x in halves) else [piece]):
                    items += _clean_item(half)
        items = list(dict.fromkeys(items))
        if len(items) >= 2:
            return items, ("any" if any_of else "all" if len(items) >= 3 else "")
    return [], ""


def extract_keywords(jd_text: str, company: str = "", extra_vocab: tuple[str, ...] = ()) -> list[Keyword]:
    segs = _segments(jd_text or "")
    counts: Counter = Counter()
    best_cls: dict[str, str] = {}
    kinds: dict[str, str] = {}
    rank = {"req": 3, "general": 2, "pref": 1, "other": 0}
    vocab_extra = tuple(BUSINESS_VOCAB) + tuple(extra_vocab)
    from_lists: set[str] = set()
    groups: dict[str, set[str]] = {}  # term -> any-of lists it appears in ("" = appears on its own somewhere)
    for li, (cls, line) in enumerate(segs):
        if cls == "other":
            continue
        low = line.lower()
        found = set(find_skills(low, extra=vocab_extra))
        items, mode = list_items(line) if cls in ("req", "pref") else ([], "")
        for it in items:
            if not any(it == f or f" {it} " in f" {f} " for f in found):
                found.add(it)
                from_lists.add(it)
        in_group = {t for t in found if mode and any(t == it or t in it or it in t for it in items)}
        for t in found:
            groups.setdefault(t, set()).add(f"{mode}{li}" if t in in_group else "")
        # drop terms that are substrings of longer found terms ("integrations" when "api integrations" present)
        found = {t for t in found if not any(t != o and f" {t} " in f" {o} " for o in found)}
        for t in found:
            counts[t] += 1
            kinds[t] = "hard"
            if rank[cls] > rank.get(best_cls.get(t, "other"), -1):
                best_cls[t] = cls
        found_text = " | ".join(found)
        for t in _dynamic_terms(line, company):
            key = t.lower()
            if key in kinds or re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", found_text):
                continue
            counts[key] += 1
            kinds.setdefault(key, "hard")
            if rank[cls] > rank.get(best_cls.get(key, "other"), -1):
                best_cls[key] = cls
        for s in SOFT_SKILLS:
            if has_soft(low, s):
                counts[s] += 1
                kinds[s] = "soft"
                if rank[cls] > rank.get(best_cls.get(s, "other"), -1):
                    best_cls[s] = cls
    out = []
    for term, n in counts.items():
        cls = best_cls.get(term, "general")
        # preferred qualifications are what separate shortlisted candidates, so they weigh nearly as much
        w = {"req": 2.0, "general": 1.5, "pref": 1.6}.get(cls, 1.0) + (0.5 if n >= 3 else 0)
        g = groups.get(term, {""})
        group = sorted(g)[0] if "" not in g else ""
        out.append(Keyword(term, kinds[term], w, cls == "req", n, group, cls))
    # dynamic one-off acronyms are noisy: keep them only if repeated or in required/preferred lists
    out = [k for k in out if not (k.term not in SKILL_VOCAB and k.term not in vocab_extra and k.kind == "hard"
                                  and k.count < 2 and k.section not in ("req", "pref") and k.term not in from_lists)]
    out.sort(key=lambda k: (-k.weight, -k.count, k.term))
    return out[:45]


# ------------------------------------------------------------------ resume facts

_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
RANGE_RE = re.compile(rf"({_MONTH}\s+\d{{4}}|\d{{1,2}}/\d{{4}}|\b\d{{4}})\s*(?:-|–|—|to)\s*({_MONTH}\s+\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}}|present|current|now)", re.I)


def resume_years(text: str) -> Optional[float]:
    from .textutil import parse_month_year

    spans = []
    for a, b in RANGE_RE.findall(text or ""):
        s, e = parse_month_year(a), parse_month_year(b)
        if s and e and e >= s and (e - s).days < 365 * 45:
            spans.append((s, e))
    if not spans:
        return None
    spans.sort()
    total, (cs, ce) = 0.0, spans[0]
    for s, e in spans[1:]:
        if s <= ce:
            ce = max(ce, e)
        else:
            total += (ce - cs).days
            cs, ce = s, e
    total += (ce - cs).days
    return round(total / 365.25, 1)


def _degree_level(text: str) -> int:
    lv = degree_levels(text)
    return max(lv) if lv else 0


# Strict patterns: bare "MS"/"BS" also mean "MS Office" or "10 ms", so they only count next to "in/of/degree" or a slash.
DEG_RX = {
    3: re.compile(r"\bph\.?\s?d\b|\bdoctorate\b|\bdoctoral\b|\bd\.phil\b", re.I),
    2: re.compile(r"\bmaster'?s?\b|\bmasters\b|\bm\.s\.|\bm\.sc\.?(?=\W|$)|\bmsc\b|\bms\s+(?:in|of|degree)\b|\bmba\b|"
                  r"\bm\.?tech\b|\bm\.eng\b|\bmeng\b|\bgraduate degree\b|\badvanced degree\b", re.I),
    1: re.compile(r"\bbachelor'?s?\b|\bbachelors\b|\bb\.s\.|\bb\.sc\.?(?=\W|$)|\bbsc\b|\bbs\s+(?:in|of|degree)\b|\bb\.a\.|"
                  r"\bba\s+(?:in|of)\b|\bb\.?tech\b|\bb\.e\.|\bundergraduate degree\b|\b(?:4|four)[- ]year degree\b|"
                  r"\bcollege degree\b|\buniversity degree\b", re.I),
}
SLASH_RX = re.compile(r"\b(bs|ba|b\.s\.?|ms|m\.s\.?|phd|ph\.d\.?)\s*/\s*(bs|ba|b\.s\.?|ms|m\.s\.?|phd|ph\.d\.?)"
                      r"(?:\s*/\s*(bs|ms|m\.s\.?|phd|ph\.d\.?))?", re.I)
_SLASH_LVL = {"b": 1, "m": 2, "p": 3}
DEGREE_NAMES = {0: "no degree listed", 1: "a bachelor's", 2: "a master's", 3: "a PhD"}
CS_FAMILY = {"computer science", "computer engineering", "software engineering", "information technology",
             "information systems", "electrical engineering", "data science", "statistics", "mathematics", "engineering"}


def degree_levels(text: str) -> set[int]:
    t = text or ""
    out = {lvl for lvl, rx in DEG_RX.items() if rx.search(t)}
    for m in SLASH_RX.finditer(t):
        out |= {_SLASH_LVL[g.lower()[0]] for g in m.groups() if g}
    # "BS, MS or PhD in …": bare abbreviations in a list, only where the sentence is clearly about degrees
    if re.search(r"degree|ph\.?d|science|engineering|field|discipline|equivalent", t, re.I):
        for m in re.finditer(r"\b(bs|ba|ms|m\.s|b\.s)\b(?=\s*(?:,|/|\bor\b|\band\b))", t, re.I):
            out.add(_SLASH_LVL[m.group(1).lower()[0]])
    return out


def _sentences(jd: str):
    """(section, sentence) pairs; unlike _segments, a 'preferred' word only affects its own sentence."""
    cls = "general"
    for raw in (jd or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        short = len(line) < 70 and not line.endswith(".")
        if short and OTHER_HDR.search(line):
            cls = "other"
        elif short and PREF_HDR.search(line):
            cls = "pref"
        elif short and REQ_HDR.search(line):
            cls = "req"
        for part in re.split(r"(?<=[.;•])\s+|\s+[•·]\s+", line):
            if part.strip():
                yield cls, part.strip()


def degree_requirement(jd: str) -> dict:
    """What the posting asks for. Any degree in a list ("BS/MS/PhD", "Master's or PhD") qualifies, so a
    requirement line counts at its lowest level; "preferred"/"plus" lines don't make a degree required."""
    req_levels, pref, equiv, related = [], 0, False, False
    for cls, sent in _sentences(jd):
        if cls == "other":
            continue
        lv = degree_levels(sent)
        if not lv:
            continue
        if re.search(r"equivalent (?:practical |professional |work |industry )?experience|or equivalent|equivalent combination", sent, re.I):
            equiv = True
        if re.search(r"related (?:technical )?field|related discipline|technical field|stem field|quantitative field|similar field", sent, re.I):
            related = True
        if cls == "pref" or re.search(r"prefer|\bplus\b|nice to have|desired|desirable|ideally|bonus|advantage", sent, re.I):
            pref = max(pref, max(lv))
        else:
            req_levels.append(min(lv))
    low = (jd or "").lower()
    fields = [f for f in FIELDS if f in low]
    return {"required": min(req_levels) if req_levels else 0, "preferred": pref, "equivalent_ok": equiv,
            "related_ok": related or not fields, "fields": fields}


def education_match(jd: str, resume_text: str, degrees: Optional[list[str]] = None) -> dict:
    """Compare the posting's degree requirement with the candidate's highest degree.
    status: none (no requirement) | meets | exceeds | equivalent | below | unknown."""
    req = degree_requirement(jd)
    deg_text = "\n".join(degrees or [])
    have = _degree_level(deg_text) if deg_text.strip() else 0
    have = have or _degree_level(_education_part(resume_text))
    low_cv = ((deg_text + "\n" + (resume_text or "")).lower())
    cv_fields = [f for f in FIELDS if f in low_cv]
    if req["fields"]:
        field_ok = any(f in cv_fields for f in req["fields"]) or (
            req["related_ok"] and any(f in CS_FAMILY for f in cv_fields) and any(f in CS_FAMILY for f in req["fields"]))
    else:
        field_ok = True
    r, pf = req["required"], req["preferred"]
    if r == 0:
        status = "none"
        sc = 1.0 if (not pf or have >= pf) else 0.85
        note = "No degree is required" + (f" ({DEGREE_NAMES[pf]} preferred; you have {DEGREE_NAMES[have]})." if pf else ".")
    elif have == 0:
        status, sc = "unknown", 0.5
        note = f"Requires {DEGREE_NAMES[r]}; add your degree to your profile's Education section to check."
    elif have >= r:
        status = "exceeds" if have > r else "meets"
        sc = 1.0 if field_ok else 0.7
        note = f"Requires {DEGREE_NAMES[r]}" + (f" in {req['fields'][0]}" if req["fields"] else "") + f"; you have {DEGREE_NAMES[have]}"
        note += ("" if field_ok else " in a different field") + "."
    elif req["equivalent_ok"] and r == 1:
        status, sc = "equivalent", 0.6
        note = f"Requires {DEGREE_NAMES[r]} or equivalent experience; you have {DEGREE_NAMES[have]}."
    else:
        status, sc = "below", 0.1
        note = f"Requires {DEGREE_NAMES[r]}; you have {DEGREE_NAMES[have]} — this role needs a higher degree."
    return {"score": sc, "status": status, "required": r, "preferred": pf, "have": have, "field_ok": field_ok, "note": note}


def _education_part(resume_text: str) -> str:
    """The resume's education section if it has one (avoids 'worked with PhD researchers' elsewhere)."""
    t = resume_text or ""
    m = re.search(r"(?im)^\s*(education|academic background|academics|qualifications)\b.*$", t)
    if not m:
        return t
    rest = t[m.end():]
    nxt = re.search(r"(?im)^\s*(experience|work experience|professional experience|employment|projects|skills|technical skills|"
                    r"certifications|publications|awards)\b", rest)
    return rest[: nxt.start()] if nxt else rest[:1500]


def required_years(jd: str) -> Optional[int]:
    vals = [int(x) for x in re.findall(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years|yrs)", (jd or "").lower())]
    vals = [v for v in vals if 0 < v <= 20]
    return min(vals) if vals else None


_PREF_WORDS = re.compile(r"prefer|\bplus\b|nice to have|desired|desirable|ideally|bonus|advantage", re.I)
_YEARS_RX = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:\+\s*)?(?:years|yrs)", re.I)


def qualification_paths(jd: str) -> list[dict]:
    """Each degree/years combination the posting states, e.g. a preferred section with "Master's AND 6+ years"
    and "OR Bachelor's AND 8+ years" gives two preferred paths. section: req | pref."""
    out = []
    for cls, sent in _sentences(jd):
        if cls == "other":
            continue
        yrs = [int(x) for x in _YEARS_RX.findall(sent) if 0 < int(x) <= 20]
        if not yrs:
            continue
        lv = degree_levels(sent)
        section = "pref" if cls == "pref" or _PREF_WORDS.search(sent) else "req"
        out.append({"section": section, "degree": min(lv) if lv else 0, "years": min(yrs)})
    return out


def _years_for(paths: list[dict], have_degree: int) -> Optional[dict]:
    """The easiest path open to you: the fewest years among paths whose degree you hold."""
    if not paths:
        return None
    open_ = [p for p in paths if p["degree"] <= have_degree] or paths
    best = min(open_, key=lambda p: p["years"])
    alts = sorted({(p["degree"], p["years"]) for p in paths if (p["degree"], p["years"]) != (best["degree"], best["years"])})
    return {**best, "alternatives": [{"degree": d, "years": y} for d, y in alts]}


def experience_bars(jd: str, have_degree: int) -> dict:
    """Required and preferred years for someone with your degree (None when the posting states none)."""
    paths = qualification_paths(jd)
    req = _years_for([p for p in paths if p["section"] == "req"], have_degree)
    pref = _years_for([p for p in paths if p["section"] == "pref"], have_degree)
    if req and pref and pref["years"] <= req["years"]:
        pref = None
    return {"required": req, "preferred": pref}


def _path_text(p: dict) -> str:
    deg = {1: " with a bachelor's", 2: " with a master's", 3: " with a PhD"}.get(p["degree"], "")
    alts = [f"{a['years']}+ with {DEGREE_NAMES[a['degree']]}" for a in p.get("alternatives", []) if a["degree"]]
    return f"{p['years']}+ years{deg}" + (f" (or {', '.join(alts)})" if alts else "")


def experience_score(have_y: Optional[float], bars: dict) -> tuple[float, str]:
    """Full marks only at the preferred years: clearing the minimum is ~75%, the rest comes with the preferred."""
    req, pref = bars["required"], bars["preferred"]
    if not req and not pref:
        return 1.0, "Posting doesn't state years of experience."
    ask = "; ".join(x for x in [f"requires {_path_text(req)}" if req else "", f"prefers {_path_text(pref)}" if pref else ""] if x)
    ask = ask[0].upper() + ask[1:]
    if have_y is None:
        return 0.5, f"{ask}. No date ranges found in your resume to compare."
    r = req["years"] if req else 0
    if r and have_y < r:
        return 0.75 * have_y / r, f"{ask}. Your resume's dates add up to about {have_y} years — below the minimum."
    if not pref:
        return 1.0, f"{ask}. You have about {have_y} years — meets it."
    pf = pref["years"]
    if have_y >= pf:
        return 1.0, f"{ask}. You have about {have_y} years — meets the preferred bar."
    s = 0.75 + 0.25 * max(0.0, (have_y - r) / (pf - r))
    short = round(pf - have_y, 1)
    return s, f"{ask}. You have about {have_y} years: {'meets the minimum, ' if r else ''}{short:g} short of the preferred."


TITLE_NOISE = {"senior", "sr", "junior", "jr", "staff", "lead", "principal", "ii", "iii", "iv", "i", "associate",
               "intern", "internship", "remote", "hybrid", "contract", "full", "time", "part", "new", "grad"}


def _role_part(job_title: str) -> str:
    """'Senior Software Engineer - MDASH' -> 'Senior Software Engineer': a one-word suffix after a dash or in
    parentheses is a team / product / requisition tag, not part of the role."""
    t = re.sub(r"\s*\((?:[^()\s]+)\)\s*$", "", job_title or "")
    m = re.match(r"^(.*\S)\s+[-–—|]\s+([^\s-]+)$", t)
    return m.group(1) if m else t


def _title_score(job_title: str, resume_text: str, targets: list[str]) -> tuple[float, str]:
    core = [t for t in re.findall(r"[a-z0-9+#]+", _role_part(job_title).lower()) if t not in TITLE_NOISE and t not in STOPWORDS]
    if not core:
        return 0.5, "Job title has no distinctive words (neutral)."
    low = resume_text.lower()
    phrase = " ".join(core)
    if phrase and phrase in re.sub(r"[^a-z0-9+# ]", " ", low):
        return 1.0, f"Your resume contains the job title “{phrase}”."
    hit = [t for t in core if contains_term(low, t)]
    ratio = len(hit) / len(core)
    tgt = any(all(contains_term(t.lower(), w) for w in core) for t in targets or [])
    if tgt:
        ratio = max(ratio, 0.6)
    note = f"{len(hit)} of {len(core)} job-title words appear in your resume" + (" (title is one of your targets)." if tgt else ".")
    if ratio < 1:
        note += f" Missing: {', '.join(t for t in core if t not in hit)}."
    return round(ratio, 2), note


def _units(items: list[Keyword]) -> list[list[Keyword]]:
    """Keywords grouped for scoring: one unit per any-of list, one per standalone term."""
    by_group: dict[str, list[Keyword]] = {}
    units: list[list[Keyword]] = []
    for k in items:
        if k.group:
            if k.group not in by_group:
                by_group[k.group] = []
                units.append(by_group[k.group])
            by_group[k.group].append(k)
        else:
            units.append([k])
    return units


def _unit_weight(u: list[Keyword]) -> float:
    """A listed qualification counts a bit more than one stray keyword, but far less than all its examples."""
    return max(k.weight for k in u) * (1.5 if len(u) > 1 and u[0].group.startswith("all") else 1.0)


def _unit_share(u: list[Keyword], got: list[Keyword]) -> float:
    n = sum(1 for k in u if k in got)
    if u[0].group.startswith("all") and len(u) > 1:
        return min(1.0, n / max(2, (len(u) + 1) // 2))  # knowing half the examples is full marks
    return 1.0 if n else 0.0


def _found(norm: str, k: Keyword) -> bool:
    return has_soft(norm, k.term) if k.kind == "soft" else has_term(norm, k.term)


def score(resume_text: str, job_title: str, jd_text: str, company: str = "", weights: Optional[dict] = None,
          targets: Optional[list[str]] = None, degrees: Optional[list[str]] = None) -> dict:
    w = {"keywords": 45, "title": 15, "experience": 15, "education": 15, "soft_skills": 10}
    if weights:
        w.update({k: float(v) for k, v in weights.items() if k in w})
    norm = (resume_text or "").lower()
    kws = extract_keywords(jd_text, company)
    hard = [k for k in kws if k.kind == "hard"]
    soft = [k for k in kws if k.kind == "soft"]

    def coverage(items):
        """Weighted share of the posting's terms you have; an any-of list counts once, met by any member."""
        if not items:
            return None, [], []
        units = _units(items)
        got = [k for k in items if _found(norm, k)]
        miss = [k for u in units for k in u if k not in got and not (u[0].group.startswith("any") and any(x in got for x in u))]
        total = sum(_unit_weight(u) for u in units)
        return sum(_unit_weight(u) * _unit_share(u, got) for u in units) / total, got, miss

    hard_s, hard_got, hard_miss = coverage(hard)
    soft_s, soft_got, soft_miss = coverage(soft)
    title_s, title_note = _title_score(job_title, resume_text, targets or [])

    have_y = resume_years(resume_text)
    edu = education_match(jd_text, resume_text, degrees)
    bars = experience_bars(jd_text, edu["have"])
    exp_s, exp_note = experience_score(have_y, bars)
    edu_s, edu_note = edu["score"], edu["note"]
    pf = edu["preferred"]
    pref_bar = bars["preferred"]
    # a higher preferred degree is a gap unless a preferred path is open with your degree (e.g. "OR BS + 8 years")
    degree_gap = bool(pf and edu["have"] and edu["have"] < pf and edu["status"] in ("meets", "exceeds", "none")
                      and not (pref_bar and pref_bar["degree"] <= edu["have"] and pref_bar["degree"] > 0))
    if degree_gap:
        edu_s = min(edu_s, 0.8)
        edu_note = edu_note.rstrip(".") + f"; {DEGREE_NAMES[pf]} is preferred."

    pref_kw = [k for k in hard if k.section == "pref"]
    pref_units = _units(pref_kw)
    pref_got = [k for k in pref_kw if _found(norm, k)]
    pref_found = [u for u in pref_units if _unit_share(u, pref_got) >= 0.5]
    preferred = {
        "skills_total": len(pref_units), "skills_found": len(pref_found),
        "missing": [(" or " if u[0].group.startswith("any") else ", ").join(k.term for k in u if k not in pref_got)
                    for u in pref_units if u not in pref_found],
        "years": pref_bar["years"] if pref_bar else None,
        "meets_years": (have_y is not None and have_y >= pref_bar["years"]) if pref_bar else None,
        "degree": pf or None, "meets_degree": (not degree_gap) if pf else None,
        # the preferred degree is above yours but a preferred path with your degree exists ("OR BS + 8 years")
        "degree_route_years": pref_bar["years"] if (pf and edu["have"] and edu["have"] < pf and not degree_gap and pref_bar) else None,
    }

    comps = {
        "keywords": (hard_s if hard_s is not None else 0.5,
                     f"{sum(1 for u in _units(hard) if _unit_share(u, hard_got) >= 0.5)} of {len(_units(hard))} qualifications and keywords "
                     f"from the posting (required and preferred) appear in your resume." if hard else "No hard-skill keywords found in the posting."),
        "title": (title_s, title_note),
        "experience": (exp_s, exp_note),
        "education": (edu_s, edu_note),
        "soft_skills": (soft_s if soft_s is not None else 1.0,
                        f"{len(soft_got)} of {len(soft)} soft skills mentioned in the posting appear in your resume." if soft else "No soft skills listed."),
    }
    total_w = sum(w.values()) or 1
    total = round(100 * sum(w[k] * comps[k][0] for k in comps) / total_w)
    return {
        "score": total,
        "breakdown": {k: {"score": round(v[0], 2), "weight": w[k], "points": round(100 * w[k] * v[0] / total_w, 1),
                          "note": v[1]} for k, v in comps.items()},
        "matched": [k.term for k in hard_got],
        "missing": [k.term for k in hard_miss],
        "missing_required": [k.term for k in hard_miss if k.required],
        "soft_matched": [k.term for k in soft_got],
        "soft_missing": [k.term for k in soft_miss],
        "keywords": [{"term": k.term, "kind": k.kind, "required": k.required, "weight": k.weight, "section": k.section,
                      "any_of": k.group.startswith("any"), "found": _found(norm, k)} for k in kws],
        "resume_years": have_y,
        "education": edu,
        "experience_bars": bars,
        "preferred": preferred,
        "weights": w,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
