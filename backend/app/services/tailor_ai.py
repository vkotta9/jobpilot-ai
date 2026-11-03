"""AI resume tailoring: rewrite the summary and the job-relevant bullets in the posting's language, truthfully.

Pipeline (each step validated before anything reaches the resume):
1. Gap analysis — which of the job's skills the candidate shows (and where), which they show elsewhere but not in
   the summary, and which they don't have at all (never to be claimed).
2. Rewrite — one call to the strongest model on the user's key, with every line's real space on the page.
3. Review — a second pass as a strict recruiter: removes keyword stuffing, awkward phrasing and unsupported claims.
4. Guards — the fact guard (no new numbers or skills), a style guard (no keyword lists tacked on, no pure appends,
   no tool dumps) and the page fit check. Lines that fail are retried shorter once, otherwise left as they were.
"""
from __future__ import annotations

import logging
import re
from typing import Callable, Optional

from . import ats, llm
from .tailoring import fact_guard
from .textutil import find_skills, numbers_in

log = logging.getLogger("jobpilot.tailor_ai")

REWRITE_TASK = """You are an expert technical resume writer and ATS specialist. Tailor the candidate's resume lines below to the
target job so that both a recruiter and an applicant-tracking system see a strong, honest match.

HOW TO WRITE
- Summary (type=summary): rewrite it completely as 3-4 tight sentences in the same voice (no "I"). Sentence 1: who the
  candidate is, framed toward the target role (use the job's role wording only if the candidate's experience is genuinely
  that kind of work), with years of experience exactly as stated. Sentences 2-3: the most important job skills from
  skills_to_feature woven into what the candidate did with them, plus one concrete result taken from the resume.
  Last sentence: what they bring to this team. NEVER write "Skilled in X, Y and Z." and never end with a list of tools.
- Bullets (type=bullet): rewrite the bullets whose work relates to this job (priority=high first; up to 10). Pattern:
  strong action verb + what was built or improved + the technology (using the posting's name for it) + the result,
  with every metric kept exactly. Mirror the posting's phrasing for the SAME work (e.g. "RESTful APIs" when the bullet
  describes REST services). Work in at most 2 job keywords per bullet, and only where that bullet's work truly involved
  them. Vary the opening verbs; no "Responsible for"; no first person; no filler ("various", "leveraged synergies").
  Leave unrelated bullets unchanged (changed=false).
- Keep **double-asterisk** bold around technologies and key terms the way the original does; bold newly named
  technologies the same way.
- LENGTH: every item has max_chars = the space it has on the page. Never exceed it. For the summary use 85-100% of it;
  a bullet may grow up to max_chars but shouldn't shrink below min_chars.

TRUTHFULNESS (strict)
- Keep every number, metric, percentage, company, client, product, date and result exactly. Add no new numbers.
- Mention only skills and tools listed in candidate_skills or present in candidate_facts. job_skills_missing are NOT
  the candidate's: never claim, imply or list them.
- Don't inflate scope, seniority or ownership (no "led" for "participated", no "architected" for "developed").

Return every item id. For unchanged items return changed=false and the original text. keywords_added = job keywords
you newly worked into that line."""

REVIEW_TASK = """You are a strict senior technical recruiter reviewing tailored resume lines (original -> tailored) for the
target job. For each item return the final text and a verdict:
- "fixed": you corrected keyword stuffing (tool names crammed in or tacked on), awkward or robotic phrasing, grammar,
  a repeated opening verb, vague filler, or a claim the original line and candidate_facts don't support.
- "reverted": the tailored line makes an unsupported claim or reads worse than the original — return the ORIGINAL text.
- "ok": the tailored line is already excellent — return it unchanged.
Keep each line within max_chars, keep all numbers exactly, keep **bold** markers on technologies, and never add skills
from job_skills_missing."""

_ITEM = llm.strict_schema({"id": {"type": "string"}, "text": {"type": "string"}, "changed": {"type": "boolean"},
                           "keywords_added": {"type": "array", "items": {"type": "string"}}})
REWRITE_SCHEMA = llm.strict_schema({"items": {"type": "array", "items": _ITEM}})
REVIEW_SCHEMA = llm.strict_schema({"items": {"type": "array", "items": llm.strict_schema(
    {"id": {"type": "string"}, "text": {"type": "string"}, "verdict": {"type": "string", "enum": ["ok", "fixed", "reverted"]}})}})


def plain(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("**", "")).strip()


def gap_analysis(hard: list[str], required: set[str], full_low: str, summary_low: str, display: Callable[[str], str]) -> dict:
    """Split the job's hard skills into: shown in the resume, shown but not in the summary, and not the candidate's."""
    have, feature, missing = [], [], []
    for t in hard:
        if ats.has_term(full_low, t):
            have.append(display(t))
            if not ats.has_term(summary_low, t):
                feature.append(display(t))
        else:
            missing.append(display(t))
    req_disp = {display(t) for t in required}
    feature.sort(key=lambda d: d not in req_disp)  # the posting's must-haves first
    return {"have": have, "feature": feature[:8], "missing": missing, "required_missing": [m for m in missing if m in req_disp]}


def _last_sentence(t: str) -> str:
    parts = [x for x in re.split(r"(?<=[.!?])\s+", t.strip()) if x]
    return parts[-1] if parts else ""


def _is_tool_list(sentence: str) -> bool:
    """'Skilled in Python, Java, AWS and Docker.' — mostly short items, most of them tool names."""
    items = [x.strip(" .") for x in re.split(r",|;|\band\b", sentence) if x.strip(" .")]
    return len(items) >= 4 and sum(len(x.split()) <= 3 for x in items) >= len(items) - 1 and \
        sum(1 for x in items if find_skills(x)) >= 3


def style_problems(original: str, new: str, kind: str) -> list[str]:
    """Catch the patterns that make a tailored resume read worse: glued-on keyword lists, pure appends, tool dumps."""
    o, n = plain(original), plain(new)
    probs = []
    tacked = re.compile(r"\b(?:skilled|proficient|experienced|expertise) (?:in|with)\b[^.]*\.?$", re.I)
    if tacked.search(n) and not tacked.search(o):
        probs.append("ends with a tacked-on skills list")
    core = o.rstrip(". ")
    if n.startswith(core) and len(n) - len(core) > 15:
        probs.append("only appends words to the end instead of rewriting")
    old_tools = set(find_skills(o))
    new_tools = [x for x in find_skills(n) if x not in old_tools]
    if kind == "bullet" and len(new_tools) > 3:
        probs.append("crams in too many tools (" + ", ".join(new_tools[:5]) + ")")
    last = _last_sentence(n)
    if kind == "summary" and _is_tool_list(last) and not _is_tool_list(_last_sentence(o)):
        probs.append("ends with a list of keywords")
    return probs


def _items_payload(items: list[dict]) -> str:
    return "\n".join(f'- id={i["id"]} type={i["type"]} priority={i["priority"]} min_chars={i["min"]} max_chars={i["max"]}'
                     f'{" heading=" + repr(i["heading"]) if i.get("heading") else ""}\n  text: {i["text"]}' for i in items)


def _context(job, gap: dict, resume_text: str) -> str:
    return (f"<target_job>{job.title} at {job.company}</target_job>\n"
            f"<candidate_skills>{', '.join(gap['have'])}</candidate_skills>\n"
            f"<skills_to_feature>{', '.join(gap['feature'])}</skills_to_feature>\n"
            f"<job_skills_missing>{', '.join(gap['missing'])}</job_skills_missing>\n"
            f"<candidate_facts>\n{resume_text[:9000]}\n</candidate_facts>\n"
            + llm.untrusted("job_description", f"{job.title} at {job.company}\n{job.description_text}", 9000))


def rewrite(cfg, job, items: list[dict], gap: dict, resume_text: str) -> tuple[dict[str, dict], str]:
    payload = _context(job, gap, resume_text) + f"\n<items>\n{_items_payload(items)}\n</items>"
    out, model = llm.complete_json_best(REWRITE_TASK, payload, REWRITE_SCHEMA, cfg=cfg, name="tailored_lines")
    res = {}
    for x in out.get("items", []):
        if x.get("changed") and x.get("text") and x.get("id"):
            res[x["id"]] = {"text": x["text"].strip(), "keywords": [k for k in x.get("keywords_added") or [] if isinstance(k, str)][:6]}
    return res, model


def review(cfg, job, changes: list[dict], gap: dict, resume_text: str) -> dict[str, dict]:
    lines = "\n".join(f'- id={c["id"]} type={c["type"]} max_chars={c["max"]}\n  original: {c["original"]}\n  tailored: {c["text"]}'
                      for c in changes)
    payload = _context(job, gap, resume_text) + f"\n<items>\n{lines}\n</items>"
    out = llm.complete_json(REVIEW_TASK, payload, REVIEW_SCHEMA, cfg=cfg, name="reviewed_lines", max_attempts=1, busy_budget_s=20)
    return {x["id"]: {"text": x["text"].strip(), "verdict": x.get("verdict", "ok")} for x in out.get("items", []) if x.get("id") and x.get("text")}


def shorten(cfg, job, items: list[dict], gap: dict, resume_text: str) -> dict[str, dict]:
    """Lines that came out longer than their space: ask for the same rewrite in fewer characters."""
    task = (REWRITE_TASK + "\n\nThese rewrites were TOO LONG for the page. Return each one with the same meaning and keywords "
            "in at most max_chars characters (count carefully; cut filler words first).")
    payload = _context(job, gap, resume_text) + f"\n<items>\n{_items_payload(items)}\n</items>"
    out = llm.complete_json(task, payload, REWRITE_SCHEMA, cfg=cfg, name="shorter_lines", max_attempts=1, busy_budget_s=20)
    return {x["id"]: {"text": x["text"].strip(), "keywords": x.get("keywords_added") or []} for x in out.get("items", []) if x.get("text")}


def validate(original: str, new: str, kind: str, full_low: str, missing: list[str], max_chars: int) -> list[str]:
    # numbers may come from elsewhere in the resume (a summary citing a bullet's 30%), never from nowhere
    probs = [p for p in fact_guard(plain(original), plain(new), full_low) if not p.startswith("introduces number")]
    invented = numbers_in(plain(new)) - numbers_in(plain(original)) - numbers_in(full_low)
    if invented:
        probs.append("introduces number(s) not in your resume: " + ", ".join(sorted(invented)))
    probs += style_problems(original, new, kind)
    low = plain(new).lower()
    claimed = [m for m in missing if ats.has_term(low, m.lower()) and not ats.has_term(plain(original).lower(), m.lower())]
    if claimed:
        probs.append("claims skills that aren't in your resume: " + ", ".join(claimed))
    if len(plain(new)) > max_chars + 8:
        probs.append("too long for its space")
    return probs


def tailor_lines(cfg, job, units: list, full_text: str, gap: dict, room: Callable, fits: Callable, kind_of: Callable,
                 relevance: Callable) -> tuple[dict[str, dict], str, list[str]]:
    """Run rewrite → review → guards. Returns ({unit_id: {text, keywords, note}}, model used, notes for the user)."""
    full_low = full_text.lower()
    items = []
    for u in units:
        md = u["md"]
        n = len(plain(md))
        cap = room(u)
        typ = kind_of(u)
        items.append({"id": u["id"], "type": typ, "text": md, "heading": u.get("heading", ""),
                      "max": max(n, cap), "min": int(n * 0.85) if typ == "bullet" else int(min(cap, n) * 0.85),
                      "priority": "high" if typ == "summary" or relevance(u) >= 2 else ("medium" if relevance(u) else "low")})
    by_id = {i["id"]: i for i in items}
    notes: list[str] = []
    drafts, model = rewrite(cfg, job, items, gap, full_text)

    # 2. strict recruiter review of what changed
    changed = [{"id": k, "type": by_id[k]["type"], "max": by_id[k]["max"], "original": by_id[k]["text"], "text": v["text"]}
               for k, v in drafts.items() if k in by_id and plain(v["text"]) != plain(by_id[k]["text"])]
    if changed:
        try:
            reviewed = review(cfg, job, changed, gap, full_text)
        except llm.LLMError as e:
            reviewed = {}
            notes.append(f"The review pass was skipped ({e}).")
        for k, r in reviewed.items():
            if k not in drafts:
                continue
            if r["verdict"] == "reverted":
                drafts.pop(k)
            elif r["verdict"] == "fixed" and plain(r["text"]) != plain(by_id[k]["text"]):
                drafts[k]["text"] = r["text"]
                drafts[k]["reviewed"] = True

    # 3. guards + page fit (one shorter retry for lines that overflow)
    final: dict[str, dict] = {}
    too_long = []
    for k, d in drafts.items():
        it = by_id.get(k)
        if not it:
            continue
        probs = validate(it["text"], d["text"], it["type"], full_low, gap["missing"], it["max"])
        hard_probs = [p for p in probs if p != "too long for its space"]
        if hard_probs:
            final[k] = {"text": d["text"], "rejected": "; ".join(hard_probs), "keywords": d["keywords"]}
            continue
        if not fits(k, d["text"]):
            too_long.append({**it, "text": d["text"], "max": max(int(len(plain(d["text"])) * 0.9), int(it["max"] * 0.95))})
            continue
        final[k] = {"text": d["text"], "keywords": d["keywords"], "reviewed": d.get("reviewed", False)}
    if too_long:
        try:
            shorter = shorten(cfg, job, too_long, gap, full_text)
        except llm.LLMError:
            shorter = {}
        for it in too_long:
            s = shorter.get(it["id"])
            if s and not validate(by_id[it["id"]]["text"], s["text"], it["type"], full_low, gap["missing"], it["max"]) \
                    and fits(it["id"], s["text"]):
                final[it["id"]] = {"text": s["text"], "keywords": s["keywords"]}
            else:
                final[it["id"]] = {"text": it["text"], "too_long": True, "keywords": []}
    return final, model, notes
