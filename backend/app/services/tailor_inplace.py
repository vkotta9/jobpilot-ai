"""Tailor the user's *own* resume file for a job, keeping its exact format.

1. Analyse the uploaded PDF/DOCX into editable units (summary, bullets, skills lines).
2. Ask the AI (if connected) to re-word relevant lines in the job's language —
   same facts, same numbers, about the same length so the layout doesn't move.
   Every suggestion passes the fact guard and a fit check.
3. Suggest skills from the job description for the existing skills lines:
   skills already evidenced elsewhere in the resume are pre-selected; skills
   that aren't are listed unticked ("add only if true").
4. The user accepts/edits each change; rendering applies them to the original
   file (header, contact details and all other content stay untouched).
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from ..config import settings
from ..models import Job, Resume
from . import ats, inplace_docx, inplace_pdf, llm
from .inplace_pdf import FitError
from .tailoring import fact_guard

log = logging.getLogger("jobpilot.tailor")

GROUPS = {
    "programming": (r"program|language|coding", {"python", "java", "javascript", "typescript", "go", "rust", "c++", "c#", "c",
                    "ruby", "php", "scala", "kotlin", "swift", "r", "sql", "bash", "matlab", "perl", "dart"}),
    "web": (r"web|front|ui", {"react", "next.js", "vue", "angular", "svelte", "node.js", "express", "html", "css",
                              "tailwind", "redux", "graphql", "rest", "rest apis", "django", "flask", "fastapi", "spring",
                              "spring boot", "rails", ".net", "bootstrap"}),
    "data": (r"data|database|db|storage", {"postgresql", "mysql", "mongodb", "redis", "elasticsearch", "dynamodb", "cassandra",
                                           "sqlite", "oracle", "snowflake", "bigquery", "redshift", "databricks", "kafka", "spark",
                                           "hadoop", "airflow", "dbt", "etl", "pandas", "numpy", "tableau", "power bi", "looker"}),
    "ml": (r"machine|ml|ai|data science", {"pytorch", "tensorflow", "keras", "scikit-learn", "machine learning", "deep learning",
                                           "nlp", "computer vision", "llm", "generative ai", "rag", "langchain", "hugging face", "mlops"}),
    "cloud": (r"cloud|tool|devops|platform|infra|technolog", {"aws", "gcp", "azure", "docker", "kubernetes", "terraform",
                                                              "ansible", "jenkins", "github actions", "ci/cd", "git", "jira",
                                                              "prometheus", "grafana", "datadog", "splunk", "linux", "serverless",
                                                              "lambda", "jboss", "maven", "gradle", "postman", "azure devops"}),
    "concepts": (r"concept|core|fundamental|methodolog|practice", {"data structures", "algorithms", "oop", "system design",
                                                                   "microservices", "distributed systems", "agile", "scrum",
                                                                   "tdd", "unit testing", "testing", "api design", "sdlc"}),
    "os": (r"\bos\b|operating", {"windows", "linux", "macos", "unix"}),
}


def resume_bytes(resume: Resume) -> Optional[bytes]:
    if resume.file_data:
        return bytes(resume.file_data)
    path = settings.upload_dir / str(resume.user_id) / resume.storage_name
    return path.read_bytes() if path.exists() else None


def engine(kind: str):
    return inplace_pdf if kind == "pdf" else inplace_docx


def to_md(rich: list) -> str:
    out = []
    for t, b in rich:
        if b and t.strip():
            core = t.strip()
            lead, trail = t[: len(t) - len(t.lstrip())], t[len(t.rstrip()):]
            out.append(f"{lead}**{core}**{trail}")
        else:
            out.append(t)
    return "".join(out)


def from_md(text: str) -> list[tuple[str, bool]]:
    parts = re.split(r"(\*\*[^*]+\*\*)", text or "")
    out: list[tuple[str, bool]] = []
    for p in parts:
        if not p:
            continue
        if p.startswith("**") and p.endswith("**") and len(p) > 4:
            out.append((p[2:-2], True))
        else:
            out.append((p.replace("**", ""), False))
    return out


def plain(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("**", "")).strip()


def analyze(kind: str, data: bytes) -> list:
    return engine(kind).analyze(data)["units"]


def _display(term: str, jd: str) -> str:
    m = re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", jd, re.I)
    if m:
        s = m.group(0)
        return s if not s.islower() or len(s) > 3 else s.upper() if len(s) <= 3 else s
    return term.title() if term.islower() and len(term) > 3 else term.upper()


def _group_of(term: str) -> Optional[str]:
    t = term.lower()
    for g, (_, items) in GROUPS.items():
        if t in items:
            return g
    return None


def _assign_skill_unit(term: str, skill_units: list) -> Optional[object]:
    """Pick the skills line a new skill belongs on; never put non-OS skills on an OS line."""
    if not skill_units:
        return None
    g = _group_of(term)
    os_rx = GROUPS["os"][0]
    candidates = [u for u in skill_units if g == "os" or not (u.label and re.search(os_rx, u.label, re.I))] or skill_units
    if g:
        rx = GROUPS[g][0]
        for u in candidates:
            if u.label and re.search(rx, u.label, re.I):
                return u
        for u in candidates:  # a line already listing skills from the same group
            low = u.text.lower()
            if any(re.search(r"(?<![a-z0-9])" + re.escape(x) + r"(?![a-z0-9])", low) for x in GROUPS[g][1]):
                return u
        if g == "ml":
            for u in candidates:
                if u.label and re.search(GROUPS["concepts"][0], u.label, re.I):
                    return u
    for rx in (r"tool|technolog|other|skill|platform", GROUPS["concepts"][0]):
        for u in candidates:
            if u.label and re.search(rx, u.label, re.I):
                return u
    unlabelled = [u for u in candidates if not u.label]
    return unlabelled[0] if unlabelled else candidates[-1]


def _llm_suggestions(cfg, job: Job, items: list[dict], resume_text: str, keywords: list[str]) -> dict[str, str]:
    schema = llm.strict_schema({"items": {"type": "array", "items": llm.strict_schema(
        {"id": {"type": "string"}, "text": {"type": "string"}, "changed": {"type": "boolean"}})}})
    lines = "\n".join(f'{i["id"]} (max {i["max"]} chars, min {i["min"]} chars): {i["text"]}' for i in items)
    task = (
        "Tailor these lines of the candidate's resume to the target job. For each item return the rewritten text.\n"
        "Rules:\n"
        "- Keep every fact, number, company, tool and result exactly; do not add any tool, skill, metric or achievement "
        "that is not already in that line or in candidate_facts.\n"
        "- Use the job posting's terminology where it truthfully describes the SAME work (e.g. its words for the same concept), "
        "and put the most job-relevant part first.\n"
        f"- Job keywords you may use only when truthful: {', '.join(keywords[:30])}.\n"
        "- Stay within each item's max/min character counts so the page layout does not change.\n"
        "- Keep **double-asterisk** bold markers around the same terms when they remain.\n"
        "- If a line is already a good fit or is unrelated to the job, return it unchanged with changed=false.\n"
        "- Prefer improving the 4–8 most relevant lines; leave the rest unchanged."
    )
    payload = (f"<candidate_facts>\n{resume_text[:9000]}\n</candidate_facts>\n<items>\n{lines}\n</items>\n"
               + llm.untrusted("job_description", f"{job.title} at {job.company}\n{job.description_text}", 9000))
    out = llm.complete_json(task, payload, schema, cfg=cfg, name="tailored_lines")
    return {x["id"]: x["text"].strip() for x in out.get("items", []) if x.get("changed") and x.get("text")}


def build_plan(db, user_id: int, job: Job, resume: Resume) -> tuple[dict, list[dict], str]:
    data = resume_bytes(resume)
    if data is None:
        raise ValueError("The original resume file is missing — upload it again.")
    kind = resume.mime_type
    eng = engine(kind)
    units = eng.analyze(data)["units"]
    if not units:
        raise ValueError("Couldn't find editable sections (summary, bullets, skills) in this resume.")
    full = eng.full_text(data)
    full_low = full.lower()
    jd = job.description_text or ""
    kw = ats.extract_keywords(jd, job.company)
    hard = [k.term for k in kw if k.kind == "hard"]
    cfg = llm.config_for(db, user_id)
    flags: list[dict] = []
    generator = "rules"

    entries = []
    for u in units:
        md = to_md(u.rich)
        entries.append({"id": u.id, "kind": u.kind, "section": u.section, "heading": u.heading, "label": u.label,
                        "lines": getattr(u, "lines", None) and len(u.lines), "original": md, "proposed": None,
                        "final": md, "accepted": False, "status": "unchanged", "note": ""})
    by_id = {e["id"]: e for e in entries}
    unit_by_id = {u.id: u for u in units}

    rewritable = [u for u in units if u.kind in ("bullet", "paragraph")]
    if cfg and rewritable:
        items = []
        for u in rewritable:
            t = to_md(u.rich)
            n = len(plain(t))
            items.append({"id": u.id, "text": t, "max": int(n * 1.04) + 2, "min": int(n * 0.85)})
        try:
            sugg = _llm_suggestions(cfg, job, items, full, hard)
            generator = "ai:" + cfg.model
        except llm.LLMError as e:
            sugg = {}
            flags.append({"path": "generator", "message": f"AI suggestions unavailable: {e} Skills suggestions still work."})
        retry = []
        for uid, text in sugg.items():
            e, u = by_id.get(uid), unit_by_id.get(uid)
            if not e or plain(text) == plain(e["original"]):
                continue
            problems = fact_guard(plain(e["original"]), plain(text), full_low)
            e["proposed"] = text
            if problems:
                e["status"], e["note"] = "rejected_guard", "Not applied — " + "; ".join(problems) + ". Use it only if it's true."
                continue
            if kind == "pdf" and not inplace_pdf.fits(data, u, from_md(text))["fits"]:
                retry.append(uid)
                continue
            e["status"], e["final"], e["accepted"] = "suggested", text, True
        if retry and cfg:
            try:
                tighter = [{"id": uid, "text": by_id[uid]["proposed"], "max": int(len(plain(by_id[uid]["original"])) * 0.97),
                            "min": int(len(plain(by_id[uid]["original"])) * 0.8)} for uid in retry]
                sugg2 = _llm_suggestions(cfg, job, tighter, full, hard)
            except llm.LLMError:
                sugg2 = {}
            for uid in retry:
                e, u = by_id[uid], unit_by_id[uid]
                text = sugg2.get(uid) or e["proposed"]
                if not fact_guard(plain(e["original"]), plain(text), full_low) and inplace_pdf.fits(data, u, from_md(text))["fits"]:
                    e["proposed"], e["status"], e["final"], e["accepted"] = text, "suggested", text, True
                else:
                    e["status"], e["note"] = "too_long", "Suggestion is longer than the space on the page — shorten it to use it."
    elif not cfg:
        flags.append({"path": "generator", "message": "Connect an AI model in Settings → Connections to get sentence-level "
                      "rewrites. Without it, JobPilot only adds matching skills."})

    # skills
    skill_units = [u for u in units if u.kind == "skill_line"]
    skills_text = " ".join(u.text.lower() for u in skill_units)
    non_skill_text = "\n".join(u.text.lower() for u in units if u.kind != "skill_line") + "\n" + full_low
    skills = []
    used: dict[str, list[str]] = {}
    for term in hard:
        if ats.has_term(skills_text, term) or len(term) < 2:
            continue
        target = _assign_skill_unit(term, skill_units)
        if target is None:
            break
        evidenced = ats.has_term(non_skill_text, term)
        disp = _display(term, jd)
        fits = True
        if kind == "pdf":
            pending = used.get(target.id, []) + [disp]
            fits = inplace_pdf.free_width(target, data, ", " + ", ".join(pending)) >= 0
        if fits and evidenced:
            used.setdefault(target.id, []).append(disp)
        skills.append({"term": term, "display": disp, "unit_id": target.id, "label": target.label,
                       "evidenced": evidenced, "selected": bool(evidenced and fits), "fits": fits})
    if not skill_units:
        flags.append({"path": "skills", "message": "No skills section was found in your resume, so no skills were added."})

    content = {
        "format": "inplace", "file_kind": kind, "resume_id": resume.id, "resume_filename": resume.original_filename,
        "units": entries, "skills": skills,
        "target": {"job_id": job.id, "title": job.title, "company": job.company},
        "ats_before": _ats_summary(ats.score(full, job.title, jd, job.company)),
    }
    return content, flags, generator


def _ats_summary(a: dict) -> dict:
    return {"score": a["score"], "matched": a["matched"], "missing": a["missing"],
            "missing_required": a["missing_required"], "breakdown": {k: v for k, v in a["breakdown"].items()}}


def render(content: dict, resume: Resume) -> tuple[bytes, dict]:
    data = resume_bytes(resume)
    if data is None:
        raise ValueError("The original resume file is missing — upload it again.")
    kind = content["file_kind"]
    eng = engine(kind)
    units = eng.analyze(data)["units"]
    known = {u.id for u in units}
    edits = {}
    for e in content["units"]:
        if e["id"] in known and e.get("accepted") and plain(e["final"]) and plain(e["final"]) != plain(e["original"]):
            edits[e["id"]] = from_md(e["final"])
    adds: dict[str, list[str]] = {}
    for s in content.get("skills", []):
        if s.get("selected") and s["unit_id"] in known:
            adds.setdefault(s["unit_id"], []).append(s["display"])
    out, warnings = eng.render(data, units, edits, adds)
    return out, warnings


def ats_after(content: dict, rendered: bytes, job: Job) -> dict:
    text = engine(content["file_kind"]).full_text(rendered)
    return _ats_summary(ats.score(text, job.title, job.description_text or "", job.company))
