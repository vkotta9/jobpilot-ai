"""Resume Agent + Cover Letter Agent, with a fact guard.

Facts (employers, titles, dates, education, certifications) are copied from the
verified profile and never pass through the model. Only bullet *wording*,
bullet *order*, skills *order* and the summary may change. Every changed line is
checked by `fact_guard`; anything that introduces a number or skill not present
in the source is reverted and flagged for the user's confirmation.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from ..models import CandidateProfile, Job
from . import llm
from .matching import candidate_evidence_text
from .textutil import contains_term, find_skills, numbers_in, years_of_experience

log = logging.getLogger("jobpilot.tailoring")

PLACEHOLDER_RE = re.compile(r"\[\[ADD:[^\]]*\]\]")

_OPENER_FIXES = [
    (re.compile(r"^responsible for\s+", re.I), "Owned "),
    (re.compile(r"^worked on\s+", re.I), "Contributed to "),
    (re.compile(r"^in charge of\s+", re.I), "Led "),
    (re.compile(r"^tasked with\s+", re.I), ""),
]


def fact_guard(original: str, rewritten: str, evidence_text: str) -> list[str]:
    """Return a list of problems; empty means the rewrite introduces no new facts."""
    problems = []
    new_nums = numbers_in(rewritten) - numbers_in(original)
    if new_nums:
        problems.append("introduces number(s) not in your original: " + ", ".join(sorted(new_nums)))
    new_skills = [s for s in find_skills(rewritten) if not contains_term(evidence_text, s)]
    if new_skills:
        problems.append("mentions skill(s) not in your profile: " + ", ".join(new_skills))
    return problems


def _polish(bullet: str) -> str:
    b = bullet.strip().rstrip(".;")
    for rx, rep in _OPENER_FIXES:
        if rx.match(b):
            b = rx.sub(rep, b, count=1)
            break
    return b[:1].upper() + b[1:] if b else b


def job_keywords(job: Job, profile: CandidateProfile) -> list[str]:
    return find_skills(f"{job.title}\n{job.description_text}", extra=profile.skills or [])


def _llm_rewrite(job: Job, items: list[dict], keywords: list[str], cfg=None) -> dict[str, str]:
    schema = llm.strict_schema({
        "bullets": {"type": "array", "items": llm.strict_schema({"id": {"type": "string"}, "text": {"type": "string"}})}
    })
    facts = "\n".join(f'{i["id"]}: {i["text"]}' for i in items)
    task = (
        "Rewrite each candidate resume bullet to be clear, concise and relevant to the target job, starting with "
        "a strong verb. Keep every fact, number and tool exactly as given; do not add any. You may use terms from "
        f"this keyword list ONLY if the bullet already describes that work: {', '.join(keywords[:30])}. "
        "Return the same ids."
    )
    payload = f"<candidate_facts>\n{facts}\n</candidate_facts>\n" + llm.untrusted(
        "job_description", f"{job.title} at {job.company}\n{job.description_text}", 8000)
    out = llm.complete_json(task, payload, schema, cfg=cfg, name="bullets")
    return {b["id"]: b["text"].strip() for b in out.get("bullets", []) if b.get("text")}


def tailor_resume(profile: CandidateProfile, job: Job, resume_text: str = "", use_llm: Optional[bool] = None, cfg=None) -> tuple[dict, list[dict], str]:
    """Return (content, flags, generator)."""
    cfg = cfg or llm.env_config()
    keywords = job_keywords(job, profile)
    evidence = candidate_evidence_text(profile, resume_text)
    covered = [k for k in keywords if contains_term(evidence, k)]
    flags: list[dict] = []

    # experience: keep chronological order (as entered); reorder bullets by relevance
    experience, rewrite_items = [], []
    for ei, e in enumerate(profile.experience or []):
        scored = []
        for bi, b in enumerate(e.get("bullets", [])):
            hits = [k for k in covered if contains_term(b.lower(), k)]
            scored.append((len(hits), -bi, b, hits))
        scored.sort(reverse=True)
        bullets = []
        for rank, (_, negbi, b, hits) in enumerate(scored):
            bid = f"e{ei}b{-negbi}"
            polished = _polish(b)
            bullets.append({"id": bid, "original": b, "text": polished, "keywords": hits,
                            "changed": polished != b.strip(), "flagged": False, "note": ""})
            rewrite_items.append({"id": bid, "text": b})
        experience.append({k: e.get(k, "") for k in ("company", "title", "location", "start", "end")} | {"bullets": bullets})

    generator = "deterministic"
    want_llm = (cfg is not None) if use_llm is None else bool(use_llm and cfg is not None)
    if want_llm and rewrite_items:
        try:
            rewrites = _llm_rewrite(job, rewrite_items[:60], keywords, cfg)
            generator = "llm:" + cfg.model
            for exp in experience:
                for b in exp["bullets"]:
                    new = rewrites.get(b["id"])
                    if not new:
                        continue
                    problems = fact_guard(b["original"], new, evidence)
                    if problems:
                        b["flagged"] = True
                        b["note"] = "AI rewrite rejected — " + "; ".join(problems) + ". Kept your wording."
                        flags.append({"path": b["id"], "message": b["note"], "suggested": new})
                    else:
                        b["text"], b["changed"] = new, new != b["original"].strip()
        except llm.LLMError as e:
            log.warning("LLM tailoring failed, using deterministic output: %s", e)
            flags.append({"path": "generator", "message": f"AI unavailable ({e}); used rule-based tailoring."})

    # skills: matched-to-job first, then the rest (only skills the user listed)
    own = list(dict.fromkeys(profile.skills or []))
    in_job = [s for s in own if any(contains_term(s.lower(), k) or contains_term(k, s.lower()) for k in keywords)]
    skills = in_job + [s for s in own if s not in in_job]

    summary = (profile.summary or "").strip()
    if not summary:
        yoe = years_of_experience(profile.experience or [])
        bits = [profile.headline or (profile.experience[0].get("title") if profile.experience else "Professional")]
        if yoe:
            bits.append(f"with {int(yoe)}+ years of experience")
        line = " ".join(b for b in bits if b) + "."
        if in_job:
            line += " Skilled in " + ", ".join(in_job[:6]) + "."
        summary = line
        flags.append({"path": "summary", "message": "Summary was composed from your profile data — please review it."})

    missing = [k for k in keywords if k not in covered]
    if missing:
        flags.append({"path": "keywords", "message": "The posting mentions skills not evidenced in your profile: "
                      + ", ".join(missing[:12]) + ". They were NOT added. If you genuinely have them, add them to your profile first."})

    content = {
        "header": {"full_name": profile.full_name, "email": profile.email, "phone": profile.phone,
                   "location": profile.location, "links": profile.links or []},
        "headline": profile.headline,
        "summary": summary,
        "skills": skills,
        "experience": experience,
        "education": profile.education or [],
        "certifications": profile.certifications or [],
        "projects": profile.projects or [],
        "keywords": {"targeted": keywords, "covered": covered, "missing": missing},
        "target": {"job_id": job.id, "title": job.title, "company": job.company},
    }
    return content, flags, generator


def validate_resume_edit(original: dict, edited: dict) -> list[str]:
    """Locked fields (employers/titles/dates/education) cannot be changed via document edits."""
    problems = []
    o_exp, e_exp = original.get("experience", []), edited.get("experience", [])
    if len(o_exp) != len(e_exp):
        problems.append("Roles cannot be added or removed in a tailored resume — edit your profile instead.")
    else:
        for o, e in zip(o_exp, e_exp):
            for k in ("company", "title", "start", "end"):
                if (o.get(k) or "") != (e.get(k) or ""):
                    problems.append(f"'{k}' of {o.get('company')} is locked to your verified profile.")
    if original.get("education") != edited.get("education"):
        problems.append("Education is locked to your verified profile.")
    if original.get("certifications") != edited.get("certifications"):
        problems.append("Certifications are locked to your verified profile.")
    return problems


def cover_letter(profile: CandidateProfile, job: Job, assessment: Optional[dict], use_llm: Optional[bool] = None, cfg=None) -> tuple[dict, list[dict], str]:
    cfg = cfg or llm.env_config()
    matched = (assessment or {}).get("matched_skills", [])[:5]
    relevant = (assessment or {}).get("relevant_experience", [])[:3]
    name = profile.full_name or "[[ADD: your name]]"
    current = (profile.experience or [{}])[0] if profile.experience else {}
    flags = [{"path": "motivation", "message": "Add a genuine sentence on why you want this role/company — JobPilot will not invent your motivation."}]
    intro = (
        f"I am writing to apply for the {job.title} position at {job.company}."
        + (f" I currently work as {current.get('title')} at {current.get('company')}." if current.get("title") and current.get("company") else "")
    )
    skills_line = f" My background includes {', '.join(matched[:-1]) + ' and ' + matched[-1] if len(matched) > 1 else matched[0]}, which the role calls for." if matched else ""
    evidence_lines = [f"• At {r['company']}: {r['bullet'].rstrip('.')}." for r in relevant if r.get("company")]
    body = "\n\n".join(x for x in [
        "Dear Hiring Team,",
        intro + skills_line,
        ("A few examples of relevant work:\n" + "\n".join(evidence_lines)) if evidence_lines else "",
        f"[[ADD: why you are interested in {job.company} and this role]]",
        "I would welcome the chance to discuss how I can contribute to your team. Thank you for your time and consideration.",
        f"Sincerely,\n{name}",
    ] if x)
    generator = "deterministic"
    want_llm = (cfg is not None) if use_llm is None else bool(use_llm and cfg is not None)
    if want_llm:
        try:
            schema = llm.strict_schema({"body": {"type": "string"}})
            facts = body + "\n\nSkills: " + ", ".join(profile.skills or [])
            out = llm.complete_json(
                "Polish this cover letter draft for the target job. Keep it under 300 words. Keep every "
                "[[ADD: ...]] placeholder exactly as written. Do not add any fact not in candidate_facts.",
                f"<candidate_facts>\n{facts}\n</candidate_facts>\n"
                + llm.untrusted("job_description", job.description_text, 6000), schema, cfg=cfg, name="cover_letter")
            new = out.get("body", "").strip()
            problems = fact_guard(body, new, candidate_evidence_text(profile))
            if new and not problems and PLACEHOLDER_RE.search(new):
                body, generator = new, "llm:" + cfg.model
            elif new:
                flags.append({"path": "generator", "message": "AI draft rejected by fact guard (" + "; ".join(problems or ["placeholder removed"]) + "). Using rule-based draft."})
        except llm.LLMError as e:
            flags.append({"path": "generator", "message": f"AI unavailable ({e}); used rule-based draft."})
    return {"body": body, "target": {"job_id": job.id, "title": job.title, "company": job.company}}, flags, generator


def unresolved_placeholders(content: dict) -> list[str]:
    text = repr(content)
    return PLACEHOLDER_RE.findall(text)
