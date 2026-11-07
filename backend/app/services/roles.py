"""Role families and role tracks.

A *role track* is one resume aimed at one kind of role (e.g. a Software Engineer resume and an ML Engineer
resume). Recruiters at most US companies shortlist focused candidates, so instead of one resume that mixes
every skill, a user keeps up to three, and JobPilot scores each job against the track it belongs to.

This module is deterministic: it classifies job titles into role families, suggests which roles a resume
reads like (from its titles and skills), and picks the track a job should be scored and tailored against.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

MAX_TRACKS = 3


@dataclass(frozen=True)
class RoleFamily:
    key: str
    name: str
    titles: tuple[str, ...]  # search titles, most common first (the first ones are used for job searches)
    patterns: tuple[str, ...]  # regexes matched against a lowercase job title
    signals: tuple[str, ...] = field(default=())  # skills/phrases that make a resume read like this role


FAMILIES: tuple[RoleFamily, ...] = (
    RoleFamily(
        "ml", "Machine Learning / AI Engineer",
        ("Machine Learning Engineer", "AI Engineer", "ML Engineer", "Applied Scientist", "LLM Engineer",
         "Generative AI Engineer", "Computer Vision Engineer", "NLP Engineer", "MLOps Engineer"),
        (r"\bmachine learning\b", r"\bml\b", r"\bai\b", r"\bartificial intelligence\b", r"\bapplied scien", r"\bllm",
         r"\bgen(erative)? ?ai\b", r"\bdeep learning\b", r"\bcomputer vision\b", r"\bnlp\b", r"\bmlops\b",
         r"\bperception\b", r"\bnatural language\b"),
        ("machine learning", "deep learning", "pytorch", "tensorflow", "keras", "scikit-learn", "llm", "transformers",
         "hugging face", "computer vision", "nlp", "langchain", "rag", "fine-tuning", "model training", "mlops",
         "neural network", "generative ai", "cuda", "mlflow", "kubeflow", "sagemaker", "vertex ai", "embeddings")),
    RoleFamily(
        "research", "Research Scientist / Engineer",
        ("Research Scientist", "Research Engineer", "AI Research Scientist", "Machine Learning Researcher",
         "Applied Research Scientist"),
        (r"\bresearch (scientist|engineer)\b", r"\bresearcher\b", r"\bresearch\b.*\b(scientist|engineer)\b"),
        ("publications", "neurips", "icml", "iclr", "cvpr", "acl", "arxiv", "phd", "research", "paper", "thesis",
         "first author", "peer-reviewed")),
    RoleFamily(
        "ds", "Data Scientist",
        ("Data Scientist", "Senior Data Scientist", "Machine Learning Scientist", "Decision Scientist",
         "Product Data Scientist"),
        (r"\bdata scien", r"\bdecision scien", r"\bstatistician\b", r"\bquantitative analyst\b"),
        ("statistics", "a/b testing", "experimentation", "hypothesis testing", "regression", "pandas", "numpy",
         "r ", "causal inference", "forecasting", "data visualization", "tableau", "sql", "jupyter", "xgboost",
         "statistical modeling", "bayesian")),
    RoleFamily(
        "da", "Data / Business Analyst",
        ("Data Analyst", "Business Analyst", "Business Intelligence Analyst", "Analytics Engineer", "Product Analyst"),
        (r"\b(data|business|bi|product|marketing|financial) analyst\b", r"\banalytics\b", r"\bbusiness intelligence\b"),
        ("sql", "tableau", "power bi", "looker", "excel", "dashboards", "kpi", "reporting", "dbt", "stakeholder")),
    RoleFamily(
        "de", "Data Engineer",
        ("Data Engineer", "Big Data Engineer", "Data Platform Engineer", "ETL Developer", "Analytics Engineer"),
        (r"\bdata (engineer|platform|infrastructure|pipeline)", r"\betl\b", r"\bbig data\b", r"\bdata warehouse"),
        ("spark", "airflow", "kafka", "etl", "data pipeline", "snowflake", "databricks", "dbt", "hadoop", "bigquery",
         "redshift", "data warehouse", "data lake", "flink")),
    RoleFamily(
        "devops", "DevOps / SRE / Cloud",
        ("Site Reliability Engineer", "DevOps Engineer", "Cloud Engineer", "Platform Engineer", "Infrastructure Engineer"),
        (r"\bdevops\b", r"\bsre\b", r"\bsite reliability\b", r"\bcloud (engineer|architect)", r"\bplatform engineer",
         r"\binfrastructure engineer", r"\bdevsecops\b"),
        ("kubernetes", "docker", "terraform", "ci/cd", "jenkins", "ansible", "aws", "azure", "gcp", "prometheus",
         "grafana", "helm", "observability", "incident", "linux", "github actions")),
    RoleFamily(
        "security", "Security Engineer",
        ("Security Engineer", "Application Security Engineer", "Cloud Security Engineer", "Cybersecurity Analyst"),
        (r"\bsecurity\b", r"\bcyber", r"\bappsec\b", r"\bpenetration\b", r"\bsoc analyst\b"),
        ("security", "penetration testing", "siem", "vulnerability", "owasp", "iam", "threat", "incident response",
         "encryption", "soc 2")),
    RoleFamily(
        "mobile", "Mobile Engineer",
        ("iOS Engineer", "Android Engineer", "Mobile Software Engineer", "React Native Developer"),
        (r"\bios\b", r"\bandroid\b", r"\bmobile\b", r"\breact native\b", r"\bflutter\b"),
        ("swift", "kotlin", "ios", "android", "swiftui", "jetpack compose", "react native", "flutter", "xcode")),
    RoleFamily(
        "swe", "Software Engineer / SDE",
        ("Software Engineer", "Software Development Engineer", "Backend Engineer", "Full Stack Engineer",
         "Frontend Engineer", "Software Developer", "Java Developer", "Python Developer"),
        (r"\bsoftware\b", r"\bsde\b", r"\bswe\b", r"\bdeveloper\b", r"\bback[- ]?end\b", r"\bfront[- ]?end\b",
         r"\bfull[- ]?stack\b", r"\bprogrammer\b", r"\bweb engineer\b", r"\bapplications? engineer\b", r"\bmember of technical staff\b",
         r"\b(java|python|golang|go|\.net|c\+\+|ruby|node(\.js)?) (developer|engineer)\b", r"\bsystems? engineer"),
        ("java", "spring", "microservices", "rest api", "system design", "distributed systems", "javascript",
         "typescript", "react", "node.js", "go", "c++", "c#", ".net", "sql", "git", "object-oriented",
         "data structures", "algorithms", "unit testing", "api")),
)
BY_KEY = {f.key: f for f in FAMILIES}
_COMPILED = {f.key: [re.compile(p) for p in f.patterns] for f in FAMILIES}
# When a title fits several families the more specific role wins, in this order: "Data Scientist, ML" is data
# science, "Software Engineer, Machine Learning" is ML, "ML Research Scientist" is research.
PRIORITY = ("research", "ds", "da", "de", "ml", "devops", "security", "mobile", "swe")


def families_for_title(title: str) -> list[str]:
    """Role families a job title belongs to, most specific first ('' titles belong to none)."""
    low = (title or "").lower()
    hits = [f.key for f in FAMILIES if any(rx.search(low) for rx in _COMPILED[f.key])]
    return sorted(hits, key=PRIORITY.index)


def _count(text: str, term: str) -> int:
    t = term.strip().lower()
    if not t:
        return 0
    return len(re.findall(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", text))


def suggest_roles(resume_text: str, limit: int = 3) -> list[dict]:
    """Which roles a resume reads like: job titles it already holds count most, then the skills it lists.

    Returns [{"key", "name", "strength": 0..100, "evidence": [...], "titles": [...]}], strongest first.
    """
    low = (resume_text or "").lower()
    if not low.strip():
        return []
    head = low[:4000]  # titles live in the experience headings near the top
    out = []
    for f in FAMILIES:
        title_hits = [t for t in f.titles if _count(head, t)]
        sig = [(s, _count(low, s)) for s in f.signals]
        sig_hits = [s for s, n in sig if n]
        if not title_hits and len(sig_hits) < 2:
            continue
        pts = 30 * min(len(title_hits), 2) + 40 * min(1.0, len(sig_hits) / max(4, len(f.signals) * 0.4)) \
            + min(10, sum(n for _, n in sig))
        if f.key == "swe":  # nearly every tech resume has these; don't let the generic role crowd out the focus
            pts *= 0.8
        out.append({"key": f.key, "name": f.name, "strength": int(min(100, round(pts))),
                    "evidence": (title_hits + sig_hits)[:6], "titles": list(f.titles[:5])})
    out.sort(key=lambda r: -r["strength"])
    return out[:limit]


@dataclass
class TrackView:
    """What scoring needs from a role track (decoupled from the ORM for easy testing)."""
    id: int
    name: str
    family: str
    titles: list[str]
    resume_text: str


def track_matches_title(track: TrackView, job_title: str, families: Optional[list[str]] = None) -> bool:
    fams = families if families is not None else families_for_title(job_title)
    if track.family in fams:
        return True
    low = (job_title or "").lower()
    return any(t and t.lower() in low for t in track.titles)


def candidate_tracks(tracks: list[TrackView], job_title: str) -> tuple[list[TrackView], str]:
    """Tracks to score a job against, and why: tracks of the job's role family, else every track."""
    fams = families_for_title(job_title)
    hits = [t for t in tracks if track_matches_title(t, job_title, fams)]
    if hits:
        # 'Software Engineer, ML' matches ML and SWE tracks: keep only the most specific family present
        for fam in fams:
            spec = [t for t in hits if t.family == fam]
            if spec:
                return spec + [t for t in hits if t not in spec and t.family == "custom"], "role"
        return hits, "role"
    return list(tracks), "closest"
