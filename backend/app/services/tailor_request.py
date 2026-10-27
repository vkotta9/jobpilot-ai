"""Your own change requests on a tailored resume ("add Node.js to Backend skills",
"rewrite the H&M bullet adding 'cross-functional'", "replace Azure DevOps with Azure Pipelines").

With an AI model connected, the request is interpreted by the model (it may only change what you asked);
without one, common requests are handled by rules. Every change still has to fit the original layout,
is shown to you with its original, and can be undone like any other suggestion. Requests are your
statements about yourself, so they aren't blocked by the "not in your resume" check — but they're labelled
as your request so it's clear where they came from.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from . import ats, inplace_pdf, llm
from .textutil import SKILL_VOCAB
from .tailor_inplace import (_assign_skill_unit, _display, engine, from_md, plain, resume_bytes, split_skill_line,
                             to_md)

CMD_WORDS = {"add", "include", "put", "list", "remove", "delete", "drop", "rewrite", "change", "replace", "please", "the", "my",
             "in", "to", "into", "with", "adding", "keyword", "key", "word", "statement", "line", "bullet", "point", "work",
             "experience", "exp", "section", "skill", "skills", "set", "this", "that", "a", "an", "of", "and", "on", "for",
             "use", "using", "term", "summary", "where", "it", "says", "about"}


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+#.]+", (s or "").lower()) if w not in CMD_WORDS and len(w) > 1}


def _split_requests(text: str) -> list[str]:
    parts = re.split(r"\n+|;\s*|(?<=[.!?])\s+(?=[A-Z])", text.strip())
    return [p.strip(" .") for p in parts if p.strip(" .")]


def _skill_line(target: str, skill_entries: list[dict], units: dict, term: str):
    """Which skills line the user means ("Backend skill set" → 'Backend:' or a web/backend line)."""
    lines = [units[e["id"]] for e in skill_entries if e["id"] in units]
    tw = _words(target) - {"skills", "skill"}
    best, score = None, 0
    for u in lines:
        lw = _words(u.label)
        hit = len(tw & lw)
        if hit > score:
            best, score = u, hit
    if best is None and tw:
        aliases = {"backend": "web", "frontend": "web", "front": "web", "back": "web", "framework": "web", "frameworks": "web",
                   "language": "programming", "languages": "programming", "database": "data", "databases": "data",
                   "cloud": "cloud", "devops": "cloud", "tools": "cloud", "tool": "cloud", "ml": "ml", "ai": "ml"}
        rx = {"web": r"web|front|back|framework", "programming": r"program|language", "data": r"data|database|db",
              "cloud": r"cloud|tool|devops|platform", "ml": r"machine|ml|ai"}
        for w in tw:
            g = aliases.get(w)
            if g:
                for u in lines:
                    if u.label and re.search(rx[g], u.label, re.I):
                        return u
    return best or _assign_skill_unit(term, lines)


def _target_units(where: str, request: str, entries: list[dict], units: dict) -> list:
    """Candidate lines for a sentence request: a quoted snippet, a section name, or the best word match."""
    cands = [e for e in entries if e["kind"] in ("bullet", "paragraph") and e["id"] in units]
    q = re.findall(r"[\"“'‘]([^\"”'’]{6,})[\"”'’]", request)
    for snip in q:
        snip = snip.strip(" .…")
        hit = [e for e in cands if snip.lower() in plain(e["final"]).lower()]
        if hit:
            return hit
    w = (where or "").lower()
    if re.search(r"summary|profile|objective|about me", w):
        cands = [e for e in cands if e["kind"] == "paragraph" and re.search(r"summary|profile|objective|about", (e.get("section") or "") + (e.get("heading") or ""), re.I)] or cands
    elif re.search(r"work|exp|job|role|employ", w):
        cands = [e for e in cands if (e.get("section") or "") == "experience"] or cands
    elif re.search(r"project", w):
        cands = [e for e in cands if (e.get("section") or "") == "projects"] or cands
    rw = _words(request)
    overlap = {e["id"]: len(rw & _words(plain(e["final"]))) for e in cands}
    best = max(overlap.values(), default=0)
    if best >= 2:  # the request points at specific line(s): only those
        return [e for e in cands if overlap[e["id"]] == best]
    return sorted(cands, key=lambda e: -overlap[e["id"]])


TEAM_ADJ = r"cross[- ]functional|distributed|global|remote|agile|multidisciplinary|multi-disciplinary|international|diverse|collaborative"
TEAM_NOUNS = r"(teams?|stakeholders?|partners?|groups?|squads?|collaboration|environments?)"
TECH_NOUNS = (r"((?:backend |back-end |frontend |front-end |web |data |cloud |deployment |ci/cd |etl )?(?:systems?|services?|microservices|"
              r"applications?|apps|apis?|pipelines?|solutions?|platforms?|architectures?|infrastructure|workflows?|integrations?))")


def _insert_keyword(text: str, kw: str) -> Optional[str]:
    """Work a keyword into a line without inventing facts: an adjective goes before a fitting noun
    ("cross-functional teams", "scalable microservices"); a tool/skill is added as "using X"."""
    if re.search(r"(?<![A-Za-z])" + re.escape(kw) + r"(?![A-Za-z])", plain(text), re.I):
        return None  # already there
    tool = kw.lower() in SKILL_VOCAB or bool(re.search(r"[A-Z0-9+#./]", kw))  # Node.js, AWS, Kafka …
    if not tool:  # a describing word ("scalable", "cross-functional", "robust")
        team = re.search(TEAM_ADJ, kw, re.I)
        m = re.search(r"\b" + (TEAM_NOUNS if team else TECH_NOUNS) + r"\b", text, re.I)
        if m:
            return text[: m.start()] + kw + " " + text[m.start():]
        if team:
            body = text.rstrip()
            end = "." if body.endswith(".") else ""
            return body.rstrip(".") + f", working with {kw} teams" + end
        return None
    body = text.rstrip()
    end = "." if body.endswith(".") else ""
    return body.rstrip(".") + f" using {kw}" + end


def _rules(request: str, content: dict, units: dict, jd: str) -> tuple[list[dict], list[str]]:
    """Returns (operations, not understood)."""
    ops, unclear = [], []
    entries = content["units"]
    skill_entries = [e for e in entries if e["kind"] == "skill_line"]
    for req in _split_requests(request):
        r = req.strip()
        m = re.match(r"^(?:please\s+)?(?:replace|change|swap)\s+[\"“']?(.+?)[\"”']?\s+(?:with|to|by|for)\s+[\"“']?(.+?)[\"”']?(?:\s+in\s+(?:the\s+|my\s+)?(.+))?$", r, re.I)
        if m:
            ops.append({"op": "replace", "a": m.group(1).strip(), "b": m.group(2).strip(), "where": m.group(3) or "", "req": r})
            continue
        m = re.match(r"^(?:please\s+)?(?:remove|delete|drop|take out)\s+(.+?)\s+(?:from)\s+(?:the\s+|my\s+)?(.+)$", r, re.I)
        if m and re.search(r"skill|tool|language|framework|backend|frontend|database|cloud|technolog|:", m.group(2), re.I):
            for item in re.split(r",\s*|\s+and\s+", m.group(1)):
                if item.strip():
                    ops.append({"op": "remove_skill", "skill": item.strip(" '\"“”"), "where": m.group(2), "req": r})
            continue
        m = re.search(r"(?:add(?:ing)?|include|use|put|mention|work in)\s+(?:the\s+)?(?:key\s?word|term|word|phrase)?\s*[\"“'‘]?([A-Za-z0-9+#./ -]{2,40}?)[\"”'’]?\s*(?:key\s?word|term|word|phrase)?\s+(?:to|in|into|on|under)\s+(?:the\s+|my\s+)?(.+)$", r, re.I)
        if m:
            what, where = m.group(1).strip(), m.group(2).strip()
            if re.search(r"skill|tool|language|framework|stack|database|cloud|technolog|section", where, re.I) and not re.search(r"bullet|statement|line|sentence|point|summary|work ex|experience", where, re.I):
                for item in re.split(r",\s*|\s+and\s+", what):
                    if item.strip():
                        ops.append({"op": "add_skill", "skill": item.strip(" '\"“”"), "where": where, "req": r})
            else:
                ops.append({"op": "keyword", "kw": what, "where": where, "req": r})
            continue
        m = re.search(r"(?:^|:\s*)(?:please\s+)?(?:add|include|use|mention|work in)\s+(?:the\s+)?(?:key\s?word|term|word|phrase)\s+[\"“'‘]?([A-Za-z0-9+#./ -]{2,40}?)[\"”'’]?\s*$", r, re.I) or \
            re.search(r"^in the (?:line|bullet|statement|sentence)\b.*?:\s*(?:please\s+)?(?:add|include|use|mention)\s+[\"“'‘]?([A-Za-z0-9+#./ -]{2,40}?)[\"”'’]?\s*$", r, re.I)
        if m:
            ops.append({"op": "keyword", "kw": m.group(1).strip(), "where": r, "req": r})
            continue
        m = re.search(r"(?:rewrite|reword|update|change)\b.*?(?:with|adding|to include|including|using)\s+(?:the\s+)?(?:key\s?word|term|word)?\s*[\"“'‘]?([A-Za-z0-9+#./ -]{2,40}?)[\"”'’]?\s*(?:key\s?word|term|word)?$", r, re.I)
        if m:
            ops.append({"op": "keyword", "kw": m.group(1).strip(), "where": r, "req": r})
            continue
        unclear.append(r)
    return ops, unclear


def _llm_plan(cfg, request: str, content: dict, units: dict, job) -> tuple[list[dict], list[str], str]:
    entries = [e for e in content["units"] if e["id"] in units]
    lines = []
    for e in entries:
        n = len(plain(e["final"]))
        if e["kind"] == "skill_line":
            lines.append(f'{e["id"]} [skills line {e.get("label") or ""}]: {plain(e["final"])}')
        else:
            lines.append(f'{e["id"]} [{e.get("heading") or e.get("section")} {e["kind"]}, max {int(n * 1.05) + 3} chars]: {e["final"]}')
    schema = llm.strict_schema({
        "edits": {"type": "array", "items": llm.strict_schema({"id": {"type": "string"}, "text": {"type": "string"}})},
        "add_skills": {"type": "array", "items": llm.strict_schema({"line_id": {"type": "string"}, "skill": {"type": "string"}})},
        "remove_skills": {"type": "array", "items": llm.strict_schema({"line_id": {"type": "string"}, "skill": {"type": "string"}})},
        "not_done": {"type": "array", "items": {"type": "string"}},
    })
    task = (
        "The candidate is editing their own tailored resume and asks for specific changes (in <request>). Do exactly what they ask, "
        "and nothing else.\n"
        "- Sentence changes go in edits (id + full new text of that line). Keep every other fact, number and name in the line; "
        "stay within the line's max chars; keep **double-asterisk** bold markers where they still apply.\n"
        "- Skills to add/remove from a skills line go in add_skills/remove_skills with that line's id (never put skills in edits).\n"
        "- The request is the candidate's own statement about themselves; you may add what they explicitly ask for, but do not "
        "invent other tools, numbers or achievements.\n"
        "- If a request is unclear or can't fit, explain it briefly in not_done.\n"
        "- The job description is context only."
    )
    payload = (f"<request>\n{request[:2000]}\n</request>\n<resume_lines>\n" + "\n".join(lines) + "\n</resume_lines>\n"
               + llm.untrusted("job_description", f"{job.title} at {job.company}\n{job.description_text or ''}", 6000))
    out = llm.complete_json(task, payload, schema, cfg=cfg, name="resume_changes")
    ops = [{"op": "set", "id": x["id"], "text": x["text"], "req": request} for x in out.get("edits", []) if x.get("id") and x.get("text")]
    ops += [{"op": "add_skill", "skill": x["skill"], "line_id": x["line_id"], "req": request} for x in out.get("add_skills", []) if x.get("skill")]
    ops += [{"op": "remove_skill", "skill": x["skill"], "line_id": x["line_id"], "req": request} for x in out.get("remove_skills", []) if x.get("skill")]
    return ops, list(out.get("not_done", [])), "ai:" + cfg.model


def apply_request(db, user_id: int, content: dict, resume, job, request: str) -> tuple[dict, dict]:
    """Apply a free-text change request to a tailored resume's content. Returns (new content, result summary)."""
    data = resume_bytes(resume)
    if data is None:
        raise ValueError("The original resume file is missing — upload it again.")
    kind = content["file_kind"]
    units = {u.id: u for u in engine(kind).analyze(data)["units"]}
    content = {**content, "units": [dict(e) for e in content["units"]], "skills": [dict(s) for s in content.get("skills", [])],
               "skill_removals": [dict(r) for r in content.get("skill_removals", []) or []]}
    by_id = {e["id"]: e for e in content["units"]}
    jd = job.description_text or ""
    cfg = llm.config_for(db, user_id)
    via, unclear = "rules", []
    ops: list[dict] = []
    if cfg:
        try:
            ops, unclear, via = _llm_plan(cfg, request, content, units, job)
        except llm.LLMError as e:
            unclear.append(f"AI unavailable ({e}); used built-in rules instead.")
    if not ops:
        r_ops, r_unclear = _rules(request, content, units, jd)
        ops, unclear = r_ops, unclear + r_unclear
        if ops:
            via = "rules"
    done, skipped = [], []

    def fits(uid: str, text: str) -> bool:  # at most a barely visible (4%) font reduction for one line
        return kind != "pdf" or inplace_pdf.fits(data, units[uid], from_md(text), allow_shrink=True, min_scale=0.96)["fits"]

    def set_line(e: dict, text: str, why: str) -> bool:
        if plain(text) == plain(e["final"]):
            return False
        if not fits(e["id"], text):
            skipped.append(f"{why}: the new text is longer than the space on that line — shorten it or pick a shorter line.")
            return False
        e["proposed"], e["final"], e["accepted"], e["status"] = text, text, True, "requested"
        e["note"] = "Changed as you asked: " + why[:160]
        done.append(f"{why} → “{plain(text)[:240]}”")
        return True

    for op in ops:
        o = op["op"]
        if o == "set":
            e = by_id.get(op["id"])
            if e is None or e["kind"] == "skill_line":
                skipped.append(f"Couldn't find line {op['id']}.")
                continue
            set_line(e, op["text"], f"Rewrote a {e.get('heading') or e.get('section')} line")
        elif o == "add_skill":
            skill = op["skill"].strip()
            skill_entries = [e for e in content["units"] if e["kind"] == "skill_line"]
            target = units.get(op.get("line_id") or "") or _skill_line(op.get("where", ""), skill_entries, units, skill.lower())
            if target is None:
                skipped.append(f"Add {skill}: no skills section was found in your resume.")
                continue
            _, items = split_skill_line(target)
            if any(i.lower() == skill.lower() for i in items) or any(s["display"].lower() == skill.lower() and s.get("selected") and s["unit_id"] == target.id for s in content["skills"]):
                skipped.append(f"{skill} is already on your '{target.label or 'skills'}' line.")
                continue
            if skill.islower():
                skill = _display(skill, jd)  # "kafka" → "Kafka", "aws" → "AWS"
            ex = next((s for s in content["skills"] if s["display"].lower() == skill.lower() or s["term"] == skill.lower()), None)
            if ex:
                ex.update(unit_id=target.id, label=target.label, selected=True, placed="skills", user=True)
            else:
                content["skills"].append({"term": skill.lower(), "display": _display(skill.lower(), jd) if ats.has_term(jd.lower(), skill.lower()) else skill,
                                          "unit_id": target.id, "label": target.label, "evidenced": True, "selected": True,
                                          "fits": True, "required": False, "placed": "skills", "user": True})
            content["skill_removals"] = [r for r in content["skill_removals"] if not (r["unit_id"] == target.id and r["display"].lower() == skill.lower())]
            done.append(f"Added {skill} to your '{target.label or 'skills'}' line")
        elif o == "remove_skill":
            skill = op["skill"].strip()
            skill_entries = [e for e in content["units"] if e["kind"] == "skill_line"]
            target = units.get(op.get("line_id") or "")
            if target is None:  # the line that actually lists it
                target = next((units[e["id"]] for e in skill_entries if e["id"] in units and any(
                    i.lower() == skill.lower() for i in split_skill_line(units[e["id"]])[1])), None)
            added = [s for s in content["skills"] if s["display"].lower() == skill.lower() and s.get("selected")]
            for s in added:
                s["selected"] = False
            if target is not None and any(i.lower() == skill.lower() for i in split_skill_line(target)[1]):
                real = next(i for i in split_skill_line(target)[1] if i.lower() == skill.lower())
                content["skill_removals"] = [r for r in content["skill_removals"] if not (r["unit_id"] == target.id and r["display"] == real)]
                content["skill_removals"].append({"unit_id": target.id, "label": target.label, "display": real, "remove": True, "user": True})
                done.append(f"Removed {real} from your '{target.label or 'skills'}' line")
            elif added:
                done.append(f"Won't add {skill}")
            else:
                skipped.append(f"Remove {skill}: it isn't on any skills line.")
        elif o == "replace":
            a, b = op["a"], op["b"]
            hit = False
            for e in content["units"]:
                if e["kind"] == "skill_line" or e["id"] not in units:
                    continue
                if re.search(re.escape(a), e["final"], re.I):
                    new = re.sub(re.escape(a), b, e["final"], count=1, flags=re.I)
                    set_line(e, new, f"Replaced “{a}” with “{b}”")
                    hit = True
            for e in content["units"]:  # also on skills lines
                if e["kind"] != "skill_line" or e["id"] not in units:
                    continue
                items = split_skill_line(units[e["id"]])[1]
                real = next((i for i in items if i.lower() == a.lower()), None)
                if real:
                    content["skill_removals"].append({"unit_id": e["id"], "label": e.get("label"), "display": real, "remove": True, "user": True})
                    content["skills"].append({"term": b.lower(), "display": b, "unit_id": e["id"], "label": e.get("label"), "evidenced": True,
                                              "selected": True, "fits": True, "required": False, "placed": "skills", "user": True})
                    done.append(f"Replaced {real} with {b} on your '{e.get('label') or 'skills'}' line")
                    hit = True
            if not hit:
                skipped.append(f"Couldn't find “{a}” in your resume.")
        elif o == "keyword":
            kw = re.sub(r"^(?:(?:adding|add|the|a|an|keyword|key word|term|word|phrase)\s+)+", "", op["kw"].strip(" '\"“”"), flags=re.I)
            kw = re.sub(r"\s+(?:keyword|key word|term|word|phrase)$", "", kw, flags=re.I).strip(" '\"“”")
            if kw.islower() and kw in SKILL_VOCAB:
                kw = _display(kw, jd)  # "kafka" → "Kafka"
            placed = False
            for e in _target_units(op.get("where", ""), op["req"], content["units"], units)[:6]:
                new = _insert_keyword(e["final"], kw)
                if new and fits(e["id"], new):
                    set_line(e, new, f"Added “{kw}”")
                    placed = True
                    break
            if not placed:
                skipped.append(f"Add “{kw}”: couldn't find a natural place that fits — " +
                               ("connect an AI model for full rewrites, or " if not cfg else "") + "edit the line yourself above.")
    content.setdefault("requests", []).append({
        "text": request[:2000], "at": datetime.now(timezone.utc).isoformat(), "via": via,
        "done": done, "skipped": skipped + [u if u.startswith("AI unavailable") else (
            f"Didn't understand: “{u}”" + ("" if cfg else " — open-ended requests like rewrites need an AI model (Settings → Connections, Gemini is free)."))
            for u in unclear],
    })
    return content, content["requests"][-1]
