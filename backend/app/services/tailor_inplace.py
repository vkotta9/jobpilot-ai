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
from .textutil import SKILL_VOCAB

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



# Same concept, different words: use the posting's wording when your resume says the same thing another way.
SYNONYMS = [
    ["PostgreSQL", "Postgres"], ["Kubernetes", "K8s"], ["JavaScript", "JS"], ["Node.js", "NodeJS", "Node"],
    ["React", "React.js", "ReactJS"], ["Next.js", "NextJS"], ["Vue.js", "Vue", "VueJS"], ["Angular", "AngularJS"],
    ["RESTful APIs", "REST APIs", "RESTful services", "RESTful web services", "REST services", "REST API"],
    ["machine learning", "ML"], ["large language models", "LLMs"], ["natural language processing", "NLP"],
    ["generative AI", "GenAI", "Gen AI"], ["Amazon Web Services", "AWS"], ["Google Cloud Platform", "GCP", "Google Cloud"],
    ["Microsoft Azure", "Azure"], ["microservices", "micro-services", "microservice architecture"],
    ["CI/CD", "CI/CD pipelines", "continuous integration and delivery", "continuous integration/continuous deployment"],
    ["unit testing", "unit tests"], ["object-oriented programming", "OOP"], ["front-end", "frontend", "front end"],
    ["back-end", "backend", "back end"], ["full-stack", "full stack", "fullstack"], ["software engineer", "software developer"],
    ["data pipelines", "ETL pipelines"], ["cloud-native", "cloud native"], ["Spring Boot", "SpringBoot"],
    ["Elasticsearch", "Elastic Search"], ["scikit-learn", "sklearn"], ["TensorFlow", "Tensorflow"], ["GitHub Actions", "Github Actions"],
]


def _rx(term: str):
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.I)


def _jd_variant(group: list[str], jd: str) -> Optional[str]:
    """The variant of a synonym group the posting uses most (exactly as written there)."""
    best, n = None, 0
    for v in group:
        hits = _rx(v).findall(jd)
        if len(hits) > n:
            best, n = hits[0], len(hits)
    return best


def align_wording(md: str, jd: str) -> tuple[str, list[str]]:
    """Swap your wording for the posting's wording where both mean the same thing."""
    out, swaps = md, []
    for group in SYNONYMS:
        want = _jd_variant(group, jd)
        if not want or _rx(want).search(out):
            continue
        for v in sorted(group, key=len, reverse=True):
            if v.lower() == want.lower():
                continue
            m = _rx(v).search(out)
            if m:
                out = out[: m.start()] + want + out[m.end():]
                swaps.append(f"{m.group(0)} → {want}")
                break
    return out, swaps


def split_skill_line(unit) -> tuple[list[tuple[str, bool]], list[str]]:
    """(label runs, items) for a skills line like 'Languages: Python, Java, SQL'."""
    full = "".join(t for t, _ in unit.rich)
    cut = 0
    if unit.label:
        i = full.find(unit.label.rstrip(":").strip())
        j = full.find(":", i if i >= 0 else 0)
        cut = j + 1 if j >= 0 and j < 60 else 0
    label_runs, pos = [], 0
    for t, b in unit.rich:
        if pos >= cut:
            break
        piece = t[: max(0, cut - pos)]
        if piece:
            label_runs.append((piece, b))
        pos += len(t)
    items, depth, cur = [], 0, ""
    for ch in full[cut:]:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch in ",;|" and depth == 0:
            items.append(cur.strip())
            cur = ""
        else:
            cur += ch
    items.append(cur.strip())
    return label_runs, [x for x in items if x]


def skill_line_runs(label_runs: list[tuple[str, bool]], items: list[str]) -> list[tuple[str, bool]]:
    return list(label_runs) + [((" " if label_runs else "") + ", ".join(items), False)]


def fit_skill_line(data: bytes, unit, plan: dict, adds: list[str], keep: set, remove: Optional[set] = None) -> dict:
    """Build the skills line: the job's skills first (yours, then the added ones), then your other skills.
    Drop other skills from the end only as far as needed for everything to fit at the original font size;
    as a last resort allow a slight font reduction. `keep` = skills the user chose not to drop."""
    label_runs, items = split_skill_line(unit)
    gone = {x.lower() for x in (remove or set())}
    items = [i for i in items if i.lower() not in gone]  # skills you asked to take off
    relevant = [i for i in items if i in plan.get("relevant", [])]
    others = [i for i in items if i not in relevant]
    droppable = [i for i in plan.get("droppable", []) if i in others and i not in keep]
    dropped: list[str] = []

    def line():
        return relevant + adds + [i for i in others if i not in dropped]

    while not inplace_pdf.fits(data, unit, skill_line_runs(label_runs, line()))["fits"] and len(dropped) < len(droppable):
        dropped.append(droppable[len(dropped)])
    ok = inplace_pdf.fits(data, unit, skill_line_runs(label_runs, line()), allow_shrink=True)["fits"]
    if not ok:
        dropped = list(droppable)
        ok = inplace_pdf.fits(data, unit, skill_line_runs(label_runs, line()), allow_shrink=True)["fits"]
    return {"items": line(), "dropped": dropped, "fits": ok, "runs": skill_line_runs(label_runs, line())}


def _relevant(item: str, jd_low: str) -> bool:
    core = re.sub(r"\(.*?\)", "", item).strip().lower()
    return bool(core) and (ats.has_term(jd_low, core) or any(ats.has_term(jd_low, w) for w in re.split(r"\s*/\s*", core) if len(w) > 1))


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
        "- The summary/profile paragraph should open with the candidate's real title closest to the job's title and name the "
        "job's most important skills the candidate actually has.\n"
        "- For bullets: lead with the action and the job-relevant technology, keep the result/metric, use strong verbs.\n"
        "- If a line is already a good fit or is unrelated to the job, return it unchanged with changed=false.\n"
        "- Improve the summary and the 6–10 most relevant bullets; leave the rest unchanged."
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
            if kind == "pdf" and not inplace_pdf.fits(data, u, from_md(text), allow_shrink=True)["fits"]:
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
                if not fact_guard(plain(e["original"]), plain(text), full_low) and inplace_pdf.fits(data, u, from_md(text), allow_shrink=True)["fits"]:
                    e["proposed"], e["status"], e["final"], e["accepted"] = text, "suggested", text, True
                else:
                    e["status"], e["note"] = "too_long", "Suggestion is longer than the space on the page — shorten it to use it."
    # wording alignment (works with or without AI): use the posting's terms for the same things
    for u in rewritable:
        e = by_id[u.id]
        base = e["final"]
        new, swaps = align_wording(base, jd)
        if not swaps or fact_guard(plain(e["original"]), plain(new), full_low):
            continue
        if kind == "pdf" and not inplace_pdf.fits(data, u, from_md(new), allow_shrink=True)["fits"]:
            continue
        e["proposed"], e["final"], e["accepted"] = new, new, True
        e["status"] = "suggested" if e["status"] == "suggested" else "rules"
        e["note"] = ((e["note"] + " ") if e["note"] else "") + "Uses the posting's wording: " + ", ".join(swaps) + "."
    if not cfg:
        flags.append({"path": "generator", "message": "For full sentence rewrites of your summary and bullet points, connect a free AI "
                      "model in Settings → Connections (Google Gemini is free). Without it, JobPilot aligns your wording with the "
                      "posting, reorganises your skills and adds missing skills to your summary."})

    # skills: add the posting's skills to the matching skills line. If a line is full, make room by
    # dropping skills on it that this job doesn't mention; anything that still doesn't fit goes into the summary.
    skill_units = [u for u in units if u.kind == "skill_line"]
    skills_text = " ".join(u.text.lower() for u in skill_units)
    non_skill_text = "\n".join(u.text.lower() for u in units if u.kind != "skill_line") + "\n" + full_low
    jd_low = jd.lower()
    required = {k.term for k in kw if k.kind == "hard" and k.required}
    skills, removals = [], []
    for term in hard:
        if ats.has_term(skills_text, term) or len(term) < 2:
            continue
        if term not in SKILL_VOCAB and not re.search(r"[A-Z0-9+#./]", _display(term, jd)):
            continue  # a plain word from the posting ("payments", "platform") isn't a skill to list
        target = _assign_skill_unit(term, skill_units)
        if target is None:
            break
        evidenced = ats.has_term(non_skill_text, term)
        skills.append({"term": term, "display": _display(term, jd), "unit_id": target.id, "label": target.label,
                       "evidenced": evidenced, "selected": evidenced, "fits": True, "required": term in required, "placed": "skills"})
    skill_lines: dict[str, dict] = {}
    if kind == "pdf":
        for u in skill_units:
            mine = [x for x in skills if x["unit_id"] == u.id]
            if not mine:
                continue
            _, items = split_skill_line(u)
            relevant = [it for it in items if _relevant(it, jd_low)]
            droppable = [it for it in reversed(items) if it not in relevant]  # least relevant first: from the end
            skill_lines[u.id] = {"relevant": relevant, "droppable": droppable}
            placed: list[dict] = []
            for x in sorted([x for x in mine if x["selected"]], key=lambda x: not x["required"]):
                res = fit_skill_line(data, u, skill_lines[u.id], [y["display"] for y in placed] + [x["display"]], set())
                if res["fits"]:
                    placed.append(x)
                else:
                    x["fits"], x["selected"] = False, False
            final = fit_skill_line(data, u, skill_lines[u.id], [y["display"] for y in placed], set())
            for gone in final["dropped"]:
                removals.append({"unit_id": u.id, "label": u.label, "display": gone, "remove": True})
            for x in mine:  # unticked skills: would they fit if the user ticks them (dropping more unrelated skills)?
                if not x["selected"] and x["fits"]:
                    x["fits"] = fit_skill_line(data, u, skill_lines[u.id], [y["display"] for y in placed] + [x["display"]], set())["fits"]
        # posting skills you have that found no room on any skills line → a short line in your summary, if there's space
        overflow = [x for x in skills if x["evidenced"] and not x["fits"]]
        summary = next((u for u in units if u.kind == "paragraph" and re.search(
            r"summary|profile|objective|about", (u.section or "") + " " + (u.heading or ""), re.I)), None)
        if summary is not None and not overflow and by_id[summary.id]["status"] in ("unchanged", "rules"):
            # room left in the summary: name the job's key skills you have (shown elsewhere in your resume)
            e = by_id[summary.id]
            in_summary = plain(e["final"]).lower()
            top = [k for k in hard if ats.has_term(non_skill_text, k) and not ats.has_term(in_summary, k)][:5]
            for n in range(len(top), 1, -1):
                cand = e["final"].rstrip() + " Skilled in " + _join([_display(t, jd) for t in top[:n]]) + "."
                if inplace_pdf.fits(data, summary, from_md(cand))["fits"]:
                    e["proposed"], e["final"], e["accepted"] = cand, cand, True
                    e["status"] = "rules"
                    e["note"] = ((e["note"] + " ") if e["note"] else "") + "Names the job's key skills you have, so your summary matches the posting."
                    break
        if summary is not None and overflow:
            e = by_id[summary.id]
            want = [x["display"] for x in sorted(overflow, key=lambda x: not x["required"])]
            for n in range(len(want), 0, -1):
                cand = e["final"].rstrip() + " Skilled in " + _join(want[:n]) + "."
                if inplace_pdf.fits(data, summary, from_md(cand), allow_shrink=True)["fits"]:
                    e["proposed"], e["final"], e["accepted"] = cand, cand, True
                    e["status"] = "suggested" if e["status"] == "suggested" else "rules"
                    e["note"] = ((e["note"] + " ") if e["note"] else "") + "Added job skills that had no room in your skills section."
                    for x in overflow:
                        if x["display"] in want[:n]:
                            x["placed"] = "summary"
                    break
    if not skill_units:
        flags.append({"path": "skills", "message": "No skills section was found in your resume, so no skills were added."})

    content = {
        "format": "inplace", "file_kind": kind, "resume_id": resume.id, "resume_filename": resume.original_filename,
        "units": entries, "skills": skills, "skill_removals": removals, "skill_lines": skill_lines,
        "target": {"job_id": job.id, "title": job.title, "company": job.company},
        "ats_before": _ats_summary(ats.score(full, job.title, jd, job.company)),
    }
    return content, flags, generator


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


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
        if s.get("selected") and s["unit_id"] in known and s.get("placed", "skills") == "skills":
            adds.setdefault(s["unit_id"], []).append(s["display"])
    by_id = {u.id: u for u in units}
    asked_off: dict[str, set] = {}  # skills the user asked to remove
    for r in content.get("skill_removals", []) or []:
        if r.get("remove") and r.get("user") and r["unit_id"] in known:
            asked_off.setdefault(r["unit_id"], set()).add(r["display"])
    if kind == "pdf":
        keep_items: dict[str, set] = {}
        for r in content.get("skill_removals", []) or []:
            if not r.get("remove"):
                keep_items.setdefault(r["unit_id"], set()).add(r["display"])
        plans = content.get("skill_lines") or {}
        for uid in set(adds) | set(plans) | set(asked_off):
            if uid in edits or uid not in by_id:
                continue
            if not adds.get(uid) and not asked_off.get(uid):
                continue  # nothing added to this line: leave it exactly as it was
            res = fit_skill_line(data, by_id[uid], plans.get(uid, {}), adds.pop(uid, []), keep_items.get(uid, set()), asked_off.get(uid))
            edits[uid] = res["runs"]
    else:
        for uid, gone in asked_off.items():
            if uid in edits or uid not in by_id:
                continue
            label_runs, items = split_skill_line(by_id[uid])
            low_gone = {g.lower() for g in gone}
            edits[uid] = skill_line_runs(label_runs, [i for i in items if i.lower() not in low_gone] + adds.pop(uid, []))
    out, warnings = eng.render(data, units, edits, adds)
    return out, warnings


def ats_after(content: dict, rendered: bytes, job: Job) -> dict:
    text = engine(content["file_kind"]).full_text(rendered)
    return _ats_summary(ats.score(text, job.title, job.description_text or "", job.company))
