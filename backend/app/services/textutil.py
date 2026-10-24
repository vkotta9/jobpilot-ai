"""Text helpers shared by parsing, matching and tailoring."""
from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from typing import Iterable, Optional

# A pragmatic skills vocabulary. The candidate's own skills are always added on
# top of this, so non-tech roles still match on the user's own terms.
SKILL_VOCAB: list[str] = [
    # languages
    "python", "java", "javascript", "typescript", "go", "golang", "rust", "c++", "c#", "ruby", "php",
    "scala", "kotlin", "swift", "r", "sql", "bash", "matlab", "perl", "elixir", "haskell", "dart",
    # web / frameworks
    "react", "next.js", "vue", "angular", "svelte", "node.js", "express", "django", "flask", "fastapi",
    "spring", "rails", ".net", "graphql", "rest", "grpc", "html", "css", "tailwind", "redux",
    # data / ml
    "pandas", "numpy", "scikit-learn", "pytorch", "tensorflow", "keras", "spark", "hadoop", "airflow",
    "dbt", "kafka", "snowflake", "bigquery", "redshift", "databricks", "tableau", "power bi", "looker",
    "machine learning", "deep learning", "nlp", "computer vision", "llm", "llms", "generative ai",
    "statistics", "data analysis", "data engineering", "data science", "etl", "a/b testing",
    "rag", "langchain", "openai", "hugging face", "mlops",
    # infra
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "ansible", "linux", "ci/cd",
    "jenkins", "github actions", "prometheus", "grafana", "datadog", "serverless", "lambda",
    "microservices", "distributed systems", "networking", "security", "oauth",
    # databases
    "postgresql", "postgres", "mysql", "mongodb", "redis", "elasticsearch", "dynamodb", "cassandra",
    "sqlite", "oracle",
    # practices / general
    "agile", "scrum", "jira", "git", "testing", "unit testing", "tdd", "system design",
    "api design", "product management", "project management", "stakeholder management",
    "leadership", "mentoring", "communication", "figma", "ux", "ui design", "user research",
    "seo", "salesforce", "excel", "financial modeling", "accounting", "marketing", "sales",
    "customer success", "copywriting", "operations", "supply chain", "six sigma",
]

_ALIASES = {
    "golang": "go",
    "postgres": "postgresql",
    "llms": "llm",
    "k8s": "kubernetes",
    "node": "node.js",
    "nodejs": "node.js",
    "nextjs": "next.js",
    "sklearn": "scikit-learn",
    "js": "javascript",
    "ts": "typescript",
}

STOPWORDS = set(
    """a an the and or of to in for on with at by from as is are be this that we you our your
    will can able have has into about over under than then their them they it its not but if
    who what when where how all any each per via using use work team role job new more most
    strong experience years year plus etc including include such well other within across""".split()
)

SENIORITY_LEVELS = {
    "intern": 0, "internship": 0,
    "junior": 1, "entry": 1, "associate": 1, "graduate": 1, "jr": 1,
    "mid": 2, "intermediate": 2,
    "senior": 3, "sr": 3,
    "staff": 4, "lead": 4, "principal": 5,
    "manager": 4, "head": 5, "director": 6, "vp": 7, "chief": 8,
}


def canon_skill(s: str) -> str:
    s = s.strip().lower()
    return _ALIASES.get(s, s)


def strip_html(raw: str) -> str:
    if not raw:
        return ""
    # Greenhouse returns HTML-escaped HTML in `content`
    raw = html.unescape(raw)
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", raw)
    raw = re.sub(r"(?i)<li[^>]*>", "\n• ", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n\n", raw)
    return raw.strip()


def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9+#./ ]+", " ", (s or "").lower()).strip()


def tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9+#.]+", (s or "").lower()) if t not in STOPWORDS and len(t) > 1]


def contains_term(text_norm: str, term: str) -> bool:
    """Whole-word-ish search that handles symbols like c++, c#, .net, node.js."""
    term = canon_skill(term)
    if not term:
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])"
    if re.search(pattern, text_norm):
        return True
    # alias forms (e.g. 'golang' in text for skill 'go')
    for alias, canon in _ALIASES.items():
        if canon == term and re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", text_norm):
            return True
    return False


def find_skills(text: str, extra: Iterable[str] = ()) -> list[str]:
    t = (text or "").lower()
    found: list[str] = []
    seen = set()
    for term in list(SKILL_VOCAB) + [canon_skill(e) for e in extra if e]:
        c = canon_skill(term)
        if c in seen:
            continue
        # single-letter skills like "r" and "go" are noisy; require context
        if c in {"r", "go"}:
            if not re.search(r"(?<![a-z0-9])(%s)(?![a-z0-9])\s*(,|/|\)|programming|language|lang)" % re.escape(c), t) \
                    and not (c == "go" and "golang" in t):
                continue
        if contains_term(t, c):
            found.append(c)
            seen.add(c)
    return found


def sha256(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def job_fingerprint(company: str, title: str, location: str) -> str:
    """Cross-source duplicate key: normalized company + title + primary city."""
    comp = re.sub(r"\b(inc|llc|ltd|corp|co|gmbh|plc)\b\.?", "", normalize(company))
    ttl = re.sub(r"\s+", " ", normalize(title))
    loc = re.sub(r"\s+", " ", normalize((location or "").split(",")[0])).strip()
    return sha256(comp.strip(), ttl, loc)


def seniority_of(title: str) -> Optional[int]:
    best = None
    for tok in tokens(title):
        if tok in SENIORITY_LEVELS:
            lvl = SENIORITY_LEVELS[tok]
            best = lvl if best is None else max(best, lvl)
    if best is None and re.search(r"\b(ii|2)\b", (title or "").lower()):
        return 2
    if best is None and re.search(r"\b(iii|3)\b", (title or "").lower()):
        return 3
    return best


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def parse_month_year(s: str) -> Optional[datetime]:
    s = (s or "").strip().lower()
    if not s:
        return None
    if s in {"present", "current", "now", "today"}:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    m = re.search(r"([a-z]{3})[a-z]*\.?\s+(\d{4})", s)
    if m and m.group(1) in _MONTHS:
        return datetime(int(m.group(2)), _MONTHS[m.group(1)], 1)
    m = re.search(r"(\d{1,2})/(\d{4})", s)
    if m:
        return datetime(int(m.group(2)), max(1, min(12, int(m.group(1)))), 1)
    m = re.search(r"(\d{4})", s)
    if m:
        return datetime(int(m.group(1)), 1, 1)
    return None


def years_of_experience(experience: list[dict]) -> Optional[float]:
    """Sum of non-overlapping employment spans, in years (None if no dates)."""
    spans = []
    for e in experience or []:
        a, b = parse_month_year(e.get("start", "")), parse_month_year(e.get("end", "") or "present")
        if a and b and b >= a:
            spans.append((a, b))
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


def required_years(text: str) -> Optional[int]:
    m = re.findall(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years|yrs)", (text or "").lower())
    vals = [int(x) for x in m if 0 < int(x) <= 30]
    return min(vals) if vals else None


NUMBER_RE = re.compile(r"\$?\d[\d,.]*\s*(?:%|k|m|x|\+)?", re.I)


def numbers_in(text: str) -> set[str]:
    return {re.sub(r"[\s,]", "", n.lower()).rstrip(".") for n in NUMBER_RE.findall(text or "")}
