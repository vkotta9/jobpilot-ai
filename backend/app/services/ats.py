"""ATS-style match score: how well a resume's text matches a job description.

Applicant tracking systems rank candidates mostly by keyword overlap with the
posting, plus job title, years of experience and education. There is no single
standard algorithm, so this is a transparent estimate built the same way:

    hard skills & keywords  (default 45)  JD skills/tools/phrases found in the resume
    job title               (default 15)  posting title vs. titles in the resume
    experience              (default 15)  years required vs. years in the resume's dates
    education               (default 15)  degree level / field required vs. resume
    soft skills             (default 10)

Requirements listed under "Requirements / Qualifications / Must have" weigh
twice as much as "Preferred / Nice to have". Matching runs against the actual
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


def extract_keywords(jd_text: str, company: str = "", extra_vocab: tuple[str, ...] = ()) -> list[Keyword]:
    segs = _segments(jd_text or "")
    counts: Counter = Counter()
    best_cls: dict[str, str] = {}
    kinds: dict[str, str] = {}
    rank = {"req": 3, "general": 2, "pref": 1, "other": 0}
    vocab_extra = tuple(BUSINESS_VOCAB) + tuple(extra_vocab)
    for cls, line in segs:
        if cls == "other":
            continue
        low = line.lower()
        found = set(find_skills(low, extra=vocab_extra))
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
        w = {"req": 2.0, "general": 1.5, "pref": 1.0}.get(cls, 1.0) + (0.5 if n >= 3 else 0)
        out.append(Keyword(term, kinds[term], w, cls == "req", n))
    # dynamic one-off acronyms are noisy: keep them only if repeated or in requirements
    out = [k for k in out if not (k.term not in SKILL_VOCAB and k.term not in vocab_extra and k.kind == "hard"
                                  and k.count < 2 and not k.required)]
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
    low = (text or "").lower()
    for lvl, rx in DEGREE_LEVELS:
        if re.search(rx, low):
            return lvl
    return 0


def required_years(jd: str) -> Optional[int]:
    vals = [int(x) for x in re.findall(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years|yrs)", (jd or "").lower())]
    vals = [v for v in vals if 0 < v <= 20]
    return min(vals) if vals else None


TITLE_NOISE = {"senior", "sr", "junior", "jr", "staff", "lead", "principal", "ii", "iii", "iv", "i", "associate",
               "intern", "internship", "remote", "hybrid", "contract", "full", "time", "part", "new", "grad"}


def _title_score(job_title: str, resume_text: str, targets: list[str]) -> tuple[float, str]:
    core = [t for t in re.findall(r"[a-z0-9+#]+", job_title.lower()) if t not in TITLE_NOISE and t not in STOPWORDS]
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


def score(resume_text: str, job_title: str, jd_text: str, company: str = "", weights: Optional[dict] = None,
          targets: Optional[list[str]] = None) -> dict:
    w = {"keywords": 45, "title": 15, "experience": 15, "education": 15, "soft_skills": 10}
    if weights:
        w.update({k: float(v) for k, v in weights.items() if k in w})
    norm = (resume_text or "").lower()
    kws = extract_keywords(jd_text, company)
    hard = [k for k in kws if k.kind == "hard"]
    soft = [k for k in kws if k.kind == "soft"]

    def coverage(items):
        if not items:
            return None, [], []
        got = [k for k in items if (has_soft(norm, k.term) if k.kind == "soft" else has_term(norm, k.term))]
        miss = [k for k in items if k not in got]
        return sum(k.weight for k in got) / sum(k.weight for k in items), got, miss

    hard_s, hard_got, hard_miss = coverage(hard)
    soft_s, soft_got, soft_miss = coverage(soft)
    title_s, title_note = _title_score(job_title, resume_text, targets or [])

    req_y = required_years(jd_text)
    have_y = resume_years(resume_text)
    if req_y is None:
        exp_s, exp_note = 1.0, "Posting doesn't state required years."
    elif have_y is None:
        exp_s, exp_note = 0.5, f"Posting asks for {req_y}+ years; no date ranges found in your resume."
    else:
        exp_s = 1.0 if have_y >= req_y else max(0.0, have_y / req_y)
        exp_note = f"Posting asks for {req_y}+ years; your resume's dates add up to about {have_y} years."

    jd_lvl = 0
    for cls, line in _segments(jd_text):
        if cls in ("req", "general") and re.search(r"degree|bachelor|master|ph\.?d|b\.?s\.|m\.?s\.", line, re.I):
            jd_lvl = max(jd_lvl, _degree_level(line))
    cv_lvl = _degree_level(resume_text)
    fields = [f for f in FIELDS if f in (jd_text or "").lower()]
    field_ok = not fields or any(f in norm for f in fields)
    if jd_lvl == 0 and not fields:
        edu_s, edu_note = 1.0, "No specific degree requirement found."
    else:
        lvl_ok = cv_lvl >= jd_lvl
        edu_s = (0.7 if lvl_ok else 0.2) + (0.3 if field_ok else 0)
        names = {0: "a degree", 1: "a bachelor's", 2: "a master's", 3: "a PhD"}
        edu_note = (f"Asks for {names[jd_lvl]}" + (f" in {fields[0]}" if fields else "") + "; your resume shows "
                    + (names[cv_lvl] if cv_lvl else "no degree keywords") + ("" if field_ok or not fields else " in a different field") + ".")

    comps = {
        "keywords": (hard_s if hard_s is not None else 0.5,
                     f"{len(hard_got)} of {len(hard)} skills/keywords from the posting appear in your resume." if hard else "No hard-skill keywords found in the posting."),
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
        "keywords": [{"term": k.term, "kind": k.kind, "required": k.required, "weight": k.weight,
                      "found": has_soft(norm, k.term) if k.kind == "soft" else has_term(norm, k.term)} for k in kws],
        "resume_years": have_y,
        "weights": w,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
