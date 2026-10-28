"""Your own change requests on a tailored resume, written the way you'd say them:

    "Add Node.js to my Web skills"
    "No, remove Node.js from AI/ML and add it to Languages at the end, after TypeScript"
    "In the Apache Camel bullet add the keyword cross-functional"
    "replace JBoss with WildFly"           "remvoe php form web skils"   (typos are fine)

With an AI model connected the request is interpreted by the model, which sees the resume exactly as it is now
(including skills added earlier) and may only change what you ask. If the AI is busy, JobPilot waits and retries
before using its built-in interpreter, which understands add / remove / move / replace / keyword requests,
"it/that/them" referring to the skill you just named, positions ("at the end", "after TypeScript"), and common
typos. Every change still has to fit your layout, is labelled "your request", and can be unticked.
"""
from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone
from typing import Optional

from . import ats, inplace_pdf, llm
from .tailor_inplace import (_display, _norm_item, engine, find_item, from_md, place_items, plain, resume_bytes,
                             split_skill_line)
from .textutil import _PRETTY, SKILL_VOCAB, pretty_skill

# ------------------------------------------------------------------ words

VERBS = {
    "add": ["add", "include", "insert", "put", "list", "append", "mention", "keep"],
    "remove": ["remove", "delete", "drop", "erase", "exclude", "omit", "take", "strip", "cut"],
    "move": ["move", "shift", "transfer", "relocate"],
    "replace": ["replace", "change", "swap", "switch", "substitute", "rename"],
    "rewrite": ["rewrite", "reword", "rephrase", "improve", "update", "edit", "modify", "make"],
}
VERB_OF = {w: v for v, ws in VERBS.items() for w in ws}
VERB_OF.update({"ad": "add", "addd": "add", "inlcude": "add", "rm": "remove", "rmv": "remove", "del": "remove", "remvoe": "remove",
                "reomve": "remove", "mv": "move", "mvoe": "move", "repalce": "replace", "replcae": "replace"})
ALL_VERBS = sorted(VERB_OF, key=len, reverse=True)
PRONOUNS = {"it", "that", "this", "them", "those", "these", "same", "the same", "that one", "this one", "that skill", "it too"}
FILLER = r"\b(?:no+|nope|ok(?:ay)?|please|pls|plz|kindly|also|then|just|actually|instead|can you|could you|would you|will you|" \
         r"i want(?: you)? to|i need(?: you)? to|i'?d like(?: you)? to|i mean|means|meaning|like|so|that too|too|as well|" \
         r"for me|now|again)\b"
LINE_WORDS = {"skill", "skills", "skillset", "set", "section", "line", "list", "row", "category", "my", "the", "a", "in", "on",
              "of", "under", "to", "into", "at", "tab", "field", "part"}
SECTION_WORDS = r"summary|profile|objective|about me|bullet|statement|sentence|point|work ?ex\w*|experience|project|achievement"


def _fix_word(w: str, vocab: list[str], cutoff: float = 0.75) -> Optional[str]:
    m = difflib.get_close_matches(w.lower(), vocab, n=1, cutoff=cutoff)
    return m[0] if m else None


def _words(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9+#]+", (s or "").lower()) if len(w) > 1 or w in ("c", "r")]


def _clauses(text: str) -> list[str]:
    """Split a request into actions: new lines, sentences, and 'and/then' followed by another action word."""
    out = []
    for sent in re.split(r"\n+|;\s*|(?<=[.!?])\s+", text.strip()):
        sent = sent.strip(" .")
        if not sent:
            continue
        toks = re.split(r"(\s+)", sent)
        cur, parts = "", []
        words = [t for t in toks]
        for i, t in enumerate(words):
            w = re.sub(r"[^a-z]", "", t.lower())
            prev = re.sub(r"[^a-z,]", "", "".join(words[max(0, i - 2):i]).lower())
            is_verb = bool(w) and (w in VERB_OF or (len(w) > 4 and _fix_word(w, ALL_VERBS, 0.8)))
            if is_verb and cur.strip() and re.search(r"(and|then|also|,)$", prev.strip()):
                parts.append(re.sub(r"(?:,|\band\b|\bthen\b|\balso\b)\s*$", "", cur.strip(), flags=re.I).strip())
                cur = ""
            cur += t
        if cur.strip():
            parts.append(cur.strip())
        out += [p.strip(" ,.") for p in parts if p.strip(" ,.")]
    return out


def _verb(clause: str) -> tuple[Optional[str], str]:
    """(action, rest of the clause) — tolerant of fillers ('No please …') and typos ('remvoe', 'ad')."""
    c = re.sub(FILLER, " ", clause, flags=re.I)
    c = re.sub(r"^\W+", "", re.sub(r"\s+", " ", c)).strip()
    m = re.match(r"([A-Za-z]+)\s*(.*)$", c)
    if not m:
        return None, c
    w, rest = m.group(1).lower(), m.group(2)
    v = VERB_OF.get(w) or (VERB_OF.get(_fix_word(w, ALL_VERBS, 0.7) or "") if len(w) > 2 else None)
    if v == "remove" and w == "take":
        rest = re.sub(r"^(?:out|off|away)\s+", "", rest, flags=re.I)
    if v is None:  # "In the line "…": add X" / "for the Camel bullet, add X"
        m2 = re.search(r"[:,]\s*([A-Za-z]+)\s+(.*)$", c)
        if m2:
            w2 = m2.group(1).lower()
            v = VERB_OF.get(w2) or VERB_OF.get(_fix_word(w2, ALL_VERBS, 0.75) or "")
            if v:
                return v, m2.group(2) + " || " + c[: m2.start()]
    return v, rest


POS_RX = [
    (re.compile(r"\b(?:right\s+|just\s+)?after\s+(?:the\s+)?[\"“'‘]?([A-Za-z0-9+#./ -]+?)[\"”'’]?(?=$|,|\s+(?:in|on|to|into|under|at|from)\b)", re.I), "after"),
    (re.compile(r"\b(?:right\s+|just\s+)?before\s+(?:the\s+)?[\"“'‘]?([A-Za-z0-9+#./ -]+?)[\"”'’]?(?=$|,|\s+(?:in|on|to|into|under|at|from)\b)", re.I), "before"),
    (re.compile(r"\b(?:at\s+the\s+)?(?:very\s+)?(?:end|last|bottom)\b|\bat\s+last\b|\blastly\b", re.I), "end"),
    (re.compile(r"\b(?:at\s+the\s+)?(?:very\s+)?(?:start|beginning|front|top|first)\b", re.I), "start"),
]


def _position(rest: str) -> tuple[Optional[dict], str]:
    pos = None
    for rx, where in POS_RX:
        m = rx.search(rest)
        if m:
            if where in ("after", "before"):
                pos = {"where": where, "ref": m.group(1).strip()}  # "after X" wins over "at the end"
            elif pos is None:
                pos = {"where": where, "ref": ""}
            rest = rest[: m.start()] + " " + rest[m.end():]
    rest = re.sub(r"\b(?:to|at|in|on)(?:\s+the)?\s*(?=$|,)", " ", re.sub(r"\s+", " ", rest).strip())  # "move X to the [end]"
    return pos, re.sub(r"\s+", " ", rest).strip(" ,")


def _split_items(obj: str) -> list[str]:
    obj = re.sub(r"^(?:the\s+)?(?:skills?|tools?|keywords?|words?|terms?)\s+", "", obj.strip(), flags=re.I)
    items = [x.strip(" '\"“”‘’.") for x in re.split(r",\s*|\s+and\s+|\s*&\s*|\s*/\s*(?=[A-Z])", obj) if x.strip(" '\"“”‘’.")]
    return items


def _canon_skill(name: str) -> str:
    """Typos and casing: 'kubernets' → 'Kubernetes', 'nodejs' → 'Node.js', 'aws' → 'AWS'. What you typed with your own
    capitals is kept ('Express.js'); unknown names are kept as typed."""
    n = name.strip()
    known = {_norm_item(v): v for v in list(SKILL_VOCAB) + list(_PRETTY)}
    if _norm_item(n) in known:
        v = known[_norm_item(n)]
        return n if (n != n.lower() and n != n.upper() and len(n) > 3) else pretty_skill(v)
    low = n.lower()
    m = difflib.get_close_matches(low, list(known.values()), n=1, cutoff=0.86) if len(low) > 4 else []
    return pretty_skill(m[0]) if m else n


# ------------------------------------------------------------------ the resume as it is now

def current_skill_lines(content: dict, units: dict) -> list[dict]:
    """Every skills line with the skills it has right now (original − removed + added), in display order."""
    out = []
    for e in content["units"]:
        if e["kind"] != "skill_line" or e["id"] not in units:
            continue
        u = units[e["id"]]
        _, items = split_skill_line(u)
        gone = {_norm_item(r["display"]) for r in content.get("skill_removals", []) or [] if r.get("remove") and r["unit_id"] == u.id}
        items = [i for i in items if _norm_item(i) not in gone]
        adds = [s for s in content.get("skills", []) if s.get("selected") and s["unit_id"] == u.id and s.get("placed", "skills") == "skills"]
        items = place_items(items + [s["display"] for s in adds if not s.get("position")],
                            [(s["display"], s["position"]) for s in adds if s.get("position")])
        out.append({"id": u.id, "label": (u.label or "Skills").rstrip(":"), "unit": u, "items": items})
    return out


def _line_for(target: str, lines: list[dict]) -> Optional[dict]:
    """The skills line the user means: 'AI/Ml', 'the Language', 'backend skill set', 'Databses' …"""
    tw = [w for w in _words(target) if w not in LINE_WORDS]
    if not tw or not lines:
        return None
    aliases = {"backend": "web", "back": "web", "frontend": "web", "front": "web", "frameworks": "web", "framework": "web",
               "language": "programming", "languages": "programming", "lang": "programming", "coding": "programming",
               "programming": "language", "database": "data", "databases": "data", "db": "data", "dbs": "data",
               "devops": "cloud", "tool": "tools", "tooling": "tools", "ml": "machine", "ai": "ml", "os": "operating"}
    best, best_s = None, 0.0
    for ln in lines:
        lw = _words(ln["label"])
        s = 0.0
        for w in tw:
            cands = [w, aliases.get(w, "")]
            sc = max((difflib.SequenceMatcher(None, c, x).ratio() for c in cands if c for x in lw), default=0)
            if any(c and any(x.startswith(c) or c.startswith(x) for x in lw if len(x) > 1 and len(c) > 1) for c in cands):
                sc = max(sc, 0.9)
            s += sc if sc >= 0.72 else 0
        if s > best_s:
            best, best_s = ln, s
    return best


def _line_with(item: str, lines: list[dict]) -> Optional[dict]:
    return next((ln for ln in lines if find_item(ln["items"], item) is not None), None)


# ------------------------------------------------------------------ built-in interpreter

def _rules(request: str, content: dict, units: dict) -> tuple[list[dict], list[str]]:
    ops, unclear = [], []
    last: list[str] = []  # what "it / that / them" refers to
    lines = current_skill_lines(content, units)
    for clause in _clauses(request):
        v, rest = _verb(clause)
        where_hint = ""
        if " || " in rest:
            rest, where_hint = rest.split(" || ", 1)
        if v is None:
            unclear.append(clause)
            continue
        pos, rest = _position(rest)
        if v == "replace":
            m = re.match(r"(?:the\s+)?[\"“'‘]?(.+?)[\"”'’]?\s+(?:with|to|by|for|into)\s+[\"“'‘]?(.+?)[\"”'’]?(?:\s+(?:in|on)\s+(?:the\s+|my\s+)?(.+))?$", rest, re.I)
            if not m:
                unclear.append(clause)
                continue
            a, b = m.group(1).strip(), m.group(2).strip()
            if a.lower() in PRONOUNS and last:
                a = last[0]
            ops.append({"op": "replace", "a": a, "b": b, "where": m.group(3) or "", "req": clause})
            last = [b]
            continue
        if v == "rewrite":
            m = re.search(r"(?:with|adding|to include|including|using|add)\s+(?:the\s+)?(?:key\s?word|term|word|phrase)?\s*[\"“'‘]?([A-Za-z0-9+#./ -]{2,40}?)[\"”'’]?\s*(?:key\s?word|term|word)?$", rest, re.I)
            if m:
                ops.append({"op": "keyword", "kw": m.group(1).strip(), "where": rest + " " + where_hint, "req": clause})
            else:
                unclear.append(clause)
            continue
        # add / remove / move: OBJECT [from SRC] [to|in|into|under|on DEST]
        src = dest = ""
        m = re.search(r"\b(?:from|form|frm|off)\s+(?:the\s+|my\s+)?(.+?)(?=\s+(?:to|in|into|under|on|onto)\s+|$)", rest, re.I)
        if m:
            src = m.group(1).strip()
            rest = rest[: m.start()] + " " + rest[m.end():]
        m = re.search(r"\b(?:to|in|into|under|on|onto|inside|within)\s+(?:the\s+|my\s+)?(.+)$", rest, re.I)
        if m:
            dest = m.group(1).strip()
            rest = rest[: m.start()]
        obj = re.sub(r"\s+", " ", rest).strip(" ,")
        if v == "add" and re.search(r"\b(?:key\s?word|term|word|phrase)\b", obj, re.I) or (
                v == "add" and re.search(SECTION_WORDS, dest + " " + where_hint, re.I) and not re.search(r"skill", dest, re.I)):
            kw = re.sub(r"\b(?:the|a|an|key\s?word|term|word|phrase)\b", " ", obj, flags=re.I).strip(" '\"“”‘’")
            if kw.lower() in PRONOUNS and last:
                kw = last[0]
            if kw:
                ops.append({"op": "keyword", "kw": kw, "where": dest + " " + where_hint, "req": clause})
                last = [kw]
            else:
                unclear.append(clause)
            continue
        items = _split_items(obj) if obj and obj.lower() not in PRONOUNS else list(last)
        items = [last[0] if i.lower() in PRONOUNS and last else i for i in items]
        items = [i for i in items if i and i.lower() not in PRONOUNS and not re.fullmatch(r"(?:the|a|an|skill|skills)", i, re.I)]
        if not items:
            unclear.append(clause + " (which skill?)")
            continue
        if v == "move" and not dest:  # "move PyTorch to the end": reorder on the line it's on
            owner = _line_with(items[0], lines)
            dest = owner["label"] if owner else ""
            src = src or dest
        if v in ("remove", "move"):
            for it in items:
                ops.append({"op": "remove_skill", "skill": it, "where": src or (dest if v == "remove" else ""), "req": clause})
        if v in ("add", "move"):
            for k, it in enumerate(items):
                p = pos
                if p and k:  # "add A and B at the start / after X" keeps A before B
                    p = {"where": "after", "ref": _canon_skill(items[k - 1])}
                ops.append({"op": "add_skill", "skill": it, "where": dest, "position": p, "req": clause})
        last = items
        lines = current_skill_lines(content, units)
    return ops, unclear


# ------------------------------------------------------------------ AI interpreter

def _llm_plan(cfg, request: str, content: dict, units: dict, job) -> tuple[list[dict], list[str], str]:
    rows = []
    for ln in current_skill_lines(content, units):
        rows.append(f'{ln["id"]} [skills line "{ln["label"]}"]: {", ".join(ln["items"])}')
    for e in content["units"]:
        if e["kind"] in ("bullet", "paragraph") and e["id"] in units:
            n = len(plain(e["final"]))
            rows.append(f'{e["id"]} [{e.get("heading") or e.get("section")} {e["kind"]}, max {int(n * 1.05) + 3} chars]: {e["final"]}')
    schema = llm.strict_schema({
        "understood_as": {"type": "string"},
        "edits": {"type": "array", "items": llm.strict_schema({"id": {"type": "string"}, "text": {"type": "string"}})},
        "add_skills": {"type": "array", "items": llm.strict_schema({
            "line_id": {"type": "string"}, "skill": {"type": "string"},
            "position": {"type": "string", "description": "'' (default: end), 'end', 'start', 'after:<skill>' or 'before:<skill>'"}})},
        "remove_skills": {"type": "array", "items": llm.strict_schema({"line_id": {"type": "string"}, "skill": {"type": "string"}})},
        "not_done": {"type": "array", "items": {"type": "string"}},
    })
    task = (
        "You are the tailoring assistant inside JobPilot. The candidate is editing THEIR OWN resume and types a request in <request>. "
        "They may write casually, with typos, bad grammar, several actions in one sentence, and words like 'it/that/them' that refer "
        "to a skill they just named. Work out what they mean and do exactly that — nothing more.\n"
        "Resume lines are listed in <resume_lines> exactly as they are now (skills lines include skills added earlier).\n"
        "- 'Move X from A to B' = remove X from line A and add X to line B. 'No, …' means they're correcting an earlier change.\n"
        "- Skills: use add_skills/remove_skills with the line id. Match line names loosely ('AI/Ml' = 'AI/ML', 'the Language' = "
        "'Languages', 'backend' = a web/backend line). Spell skills correctly ('nodejs' → 'Node.js', 'kubernets' → 'Kubernetes'). "
        "Put a skill where they say: position 'end', 'start', 'after:TypeScript' or 'before:Java'.\n"
        "- Sentences: edits with the line id and the FULL new text. Keep every other fact, number and name; stay within max chars; "
        "keep **double-asterisk** bold markers where they still apply.\n"
        "- The request is the candidate's own statement about themselves: add what they explicitly ask for, but never invent other "
        "tools, numbers or achievements.\n"
        "- understood_as: one short plain sentence restating what you did. not_done: anything you couldn't do and why.\n"
        "- The job description is context only."
    )
    history = "\n".join(f"- {r['text']}" for r in (content.get("requests") or [])[-3:])
    payload = (f"<request>\n{request[:2000]}\n</request>\n" + (f"<earlier_requests>\n{history}\n</earlier_requests>\n" if history else "")
               + "<resume_lines>\n" + "\n".join(rows) + "\n</resume_lines>\n"
               + llm.untrusted("job_description", f"{job.title} at {job.company}\n{job.description_text or ''}", 5000))
    out = llm.complete_json(task, payload, schema, cfg=cfg, name="resume_changes")
    ops = [{"op": "remove_skill", "skill": x["skill"], "line_id": x["line_id"], "req": request} for x in out.get("remove_skills", []) if x.get("skill")]
    for x in out.get("add_skills", []):
        if not x.get("skill"):
            continue
        p = (x.get("position") or "").strip()
        pos = None
        if p in ("start", "end"):
            pos = {"where": p, "ref": ""}
        elif ":" in p and p.split(":", 1)[0] in ("after", "before"):
            pos = {"where": p.split(":", 1)[0], "ref": p.split(":", 1)[1].strip()}
        ops.append({"op": "add_skill", "skill": x["skill"], "line_id": x["line_id"], "position": pos, "req": request})
    ops += [{"op": "set", "id": x["id"], "text": x["text"], "req": request} for x in out.get("edits", []) if x.get("id") and x.get("text")]
    return ops, list(out.get("not_done", [])), "ai:" + cfg.model, out.get("understood_as", "")


# ------------------------------------------------------------------ applying

SKILL_TEAM_ADJ = r"cross[- ]functional|distributed|global|remote|agile|multidisciplinary|multi-disciplinary|international|diverse|collaborative"
TEAM_NOUNS = r"(teams?|stakeholders?|partners?|groups?|squads?|collaboration|environments?)"
TECH_NOUNS = (r"((?:backend |back-end |frontend |front-end |web |data |cloud |deployment |ci/cd |etl )?(?:systems?|services?|microservices|"
              r"applications?|apps|apis?|pipelines?|solutions?|platforms?|architectures?|infrastructure|workflows?|integrations?))")


def _insert_keyword(text: str, kw: str) -> Optional[str]:
    """Work a keyword into a line without inventing facts: a describing word goes before a fitting noun
    ("cross-functional teams", "scalable microservices"); a tool is added as "using X"."""
    if re.search(r"(?<![A-Za-z])" + re.escape(kw) + r"(?![A-Za-z])", plain(text), re.I):
        return None
    tool = kw.lower() in SKILL_VOCAB or bool(re.search(r"[A-Z0-9+#./]", kw))
    if not tool:
        team = re.search(SKILL_TEAM_ADJ, kw, re.I)
        m = re.search(r"\b" + (TEAM_NOUNS if team else TECH_NOUNS) + r"\b", text, re.I)
        if m:
            # "with product and design teams" → "with cross-functional product and design teams"
            pre = re.search(r"\b(?:with|across|among|alongside|between)\s+((?:[\w&/-]+\s+){1,4})$", text[: m.start()], re.I)
            if pre and re.search(r"\band\b|&|,", pre.group(1)):
                at = m.start() - len(pre.group(1))
                return text[:at] + kw + " " + text[at:]
            return text[: m.start()] + kw + " " + text[m.start():]
        if team:
            body = text.rstrip()
            return body.rstrip(".") + f", working with {kw} teams" + ("." if body.endswith(".") else "")
        return None
    body = text.rstrip()
    return body.rstrip(".") + f" using {kw}" + ("." if body.endswith(".") else "")


def _target_units(where: str, request: str, entries: list[dict], units: dict) -> list:
    cands = [e for e in entries if e["kind"] in ("bullet", "paragraph") and e["id"] in units]
    for snip in re.findall(r"[\"“'‘]([^\"”'’]{6,})[\"”'’]", request):
        snip = snip.strip(" .…")
        hit = [e for e in cands if snip.lower() in plain(e["final"]).lower()]
        if hit:
            return hit
    w = (where or "").lower() + " " + request.lower()
    if re.search(r"summary|profile|objective|about me", w):
        cands = [e for e in cands if e["kind"] == "paragraph"] or cands
    elif re.search(r"work|exp|job|role|employ", w):
        cands = [e for e in cands if (e.get("section") or "") == "experience"] or cands
    elif re.search(r"project", w):
        cands = [e for e in cands if (e.get("section") or "") == "projects"] or cands
    stop = set(VERB_OF) | LINE_WORDS | {"bullet", "statement", "sentence", "point", "keyword", "word", "term", "work", "experience",
                                        "the", "and", "with", "about", "add", "line", "where", "says", "that", "this"}
    rw = {x for x in _words(request + " " + where) if x not in stop and len(x) > 2}
    overlap = {e["id"]: len(rw & set(_words(plain(e["final"])))) for e in cands}
    best = max(overlap.values(), default=0)
    if best >= 1:
        return sorted([e for e in cands if overlap[e["id"]] == best], key=lambda e: -overlap[e["id"]])
    return cands


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
    via, unclear, understood, notes = "rules", [], "", []
    ops: list[dict] = []
    ai_not_done: list[str] = []
    if cfg:
        try:
            ops, ai_not_done, via, understood = _llm_plan(cfg, request, content, units, job)
        except llm.LLMError as e:
            notes.append(f"Your AI model was unavailable ({e}), so JobPilot's built-in interpreter handled this.")
    if not ops:
        r_ops, r_unclear = _rules(request, content, units)
        if r_ops or not ai_not_done:
            ops, unclear, via = r_ops, r_unclear, "rules"
            ai_not_done = []
    done, skipped = [], []

    def fits(uid: str, text: str) -> bool:  # at most a barely visible (4%) font reduction for one line
        return kind != "pdf" or inplace_pdf.fits(data, units[uid], from_md(text), allow_shrink=True, min_scale=0.96)["fits"]

    def set_line(e: dict, text: str, why: str) -> bool:
        if plain(text) == plain(e["final"]):
            return False
        if not fits(e["id"], text):
            skipped.append(f"{why}: that line is already full, so the new text doesn't fit — shorten it, or edit the line above.")
            return False
        e["proposed"], e["final"], e["accepted"], e["status"] = text, text, True, "requested"
        e["note"] = "Changed as you asked: " + why[:160]
        done.append(f"{why} → “{plain(text)[:240]}”")
        return True

    def pos_text(pos: Optional[dict]) -> str:
        if not pos:
            return ""
        return {"start": " at the start", "end": " at the end"}.get(pos["where"], f" {pos['where']} {pos.get('ref', '')}")

    for op in ops:
        o = op["op"]
        lines = current_skill_lines(content, units)
        if o == "set":
            e = by_id.get(op["id"])
            if e is None or e["kind"] == "skill_line":
                skipped.append(f"Couldn't find that line ({op['id']}).")
                continue
            set_line(e, op["text"], f"Rewrote a {e.get('heading') or e.get('section')} line")
        elif o == "add_skill":
            skill = _canon_skill(op["skill"])
            target = next((ln for ln in lines if ln["id"] == op.get("line_id")), None) or _line_for(op.get("where", ""), lines)
            if target is None:
                owner = _line_with(skill, lines)
                if owner is not None and op.get("position"):
                    target = owner  # "put Node.js at the end" → reorder where it already is
                elif owner is not None:
                    skipped.append(f"{skill} is already on your '{owner['label']}' line.")
                    continue
                else:
                    target = _line_for(skill, lines) or (lines[-1] if lines else None)
                    if op.get("where"):
                        skipped.append(f"Couldn't tell which skills line “{op['where']}” is, so {skill} went to '{(target or {}).get('label', '')}'.")
            if target is None:
                skipped.append(f"Add {skill}: no skills section was found in your resume.")
                continue
            here = find_item(target["items"], skill)
            if here is not None and not op.get("position"):
                skipped.append(f"{skill} is already on your '{target['label']}' line.")
                continue
            if op.get("position") and op["position"].get("ref") and find_item(target["items"], op["position"]["ref"]) is None:
                skipped.append(f"Couldn't find {op['position']['ref']} on '{target['label']}', so {skill} went at the end.")
                op["position"] = {"where": "end", "ref": ""}
            u = target["unit"]
            _, orig = split_skill_line(u)
            pos = op.get("position")
            if find_item(orig, skill) is not None:
                # it's one of your own skills on this line: move it (take the original off, add it back in place)
                real = orig[find_item(orig, skill)]
                if pos:
                    content["skill_removals"] = [r for r in content["skill_removals"] if not (r["unit_id"] == u.id and _norm_item(r["display"]) == _norm_item(real))]
                    content["skill_removals"].append({"unit_id": u.id, "label": u.label, "display": real, "remove": True, "user": True, "moved": True})
                    skill = real
                else:
                    content["skill_removals"] = [r for r in content["skill_removals"] if not (r["unit_id"] == u.id and _norm_item(r["display"]) == _norm_item(real))]
                    done.append(f"Kept {real} on your '{target['label']}' line")
                    continue
            for s in content["skills"]:  # one place per skill: un-select it elsewhere
                if _norm_item(s["display"]) == _norm_item(skill) and s["unit_id"] != u.id:
                    s["selected"] = False
            ex = next((s for s in content["skills"] if _norm_item(s["display"]) == _norm_item(skill) and s["unit_id"] == u.id), None)
            entry = {"unit_id": u.id, "label": u.label, "selected": True, "placed": "skills", "user": True, "position": pos}
            if ex:
                ex.update(entry)
            else:
                disp = _display(skill.lower(), jd) if ats.has_term(jd.lower(), skill.lower()) and skill.islower() else skill
                content["skills"].append({"term": skill.lower(), "display": disp, "evidenced": True, "fits": True, "required": False, **entry})
            done.append(f"Added {skill} to your '{target['label']}' line{pos_text(pos)}")
        elif o == "remove_skill":
            skill = op["skill"].strip()
            target = next((ln for ln in lines if ln["id"] == op.get("line_id")), None)
            if target is None and op.get("where"):
                target = _line_for(op["where"], lines)
            if target is None or find_item(target["items"], skill) is None:
                target = _line_with(skill, lines) or target
            if target is None or find_item(target["items"], skill) is None:
                skipped.append(f"Remove {skill}: it isn't on " + (f"your '{target['label']}' line." if target else "any skills line."))
                continue
            real = target["items"][find_item(target["items"], skill)]
            u = target["unit"]
            hit = False
            for s in content["skills"]:  # a skill added for this job (by JobPilot or by you)
                if s.get("selected") and s["unit_id"] == u.id and _norm_item(s["display"]) == _norm_item(real):
                    s["selected"], s["position"] = False, None
                    hit = True
            _, orig = split_skill_line(u)
            if find_item(orig, real) is not None:
                content["skill_removals"] = [r for r in content["skill_removals"] if not (r["unit_id"] == u.id and _norm_item(r["display"]) == _norm_item(real))]
                content["skill_removals"].append({"unit_id": u.id, "label": u.label, "display": orig[find_item(orig, real)], "remove": True, "user": True})
                hit = True
            if hit:
                done.append(f"Removed {real} from your '{target['label']}' line")
        elif o == "replace":
            a, b = op["a"], op["b"]
            hit = False
            for e in content["units"]:
                if e["kind"] in ("bullet", "paragraph") and e["id"] in units and re.search(re.escape(a), e["final"], re.I):
                    set_line(e, re.sub(re.escape(a), b, e["final"], count=1, flags=re.I), f"Replaced “{a}” with “{b}”")
                    hit = True
            for ln in lines:
                i = find_item(ln["items"], a)
                if i is None:
                    continue
                real, after = ln["items"][i], (ln["items"][i - 1] if i else "")
                u = ln["unit"]
                _, orig = split_skill_line(u)
                if find_item(orig, real) is not None:
                    content["skill_removals"].append({"unit_id": u.id, "label": u.label, "display": orig[find_item(orig, real)], "remove": True, "user": True})
                for s in content["skills"]:
                    if s.get("selected") and s["unit_id"] == u.id and _norm_item(s["display"]) == _norm_item(real):
                        s["selected"] = False
                content["skills"].append({"term": b.lower(), "display": _canon_skill(b), "unit_id": u.id, "label": u.label, "evidenced": True,
                                          "selected": True, "fits": True, "required": False, "placed": "skills", "user": True,
                                          "position": {"where": "after", "ref": after} if after else {"where": "start", "ref": ""}})
                done.append(f"Replaced {real} with {_canon_skill(b)} on your '{ln['label']}' line")
                hit = True
            if not hit:
                skipped.append(f"Couldn't find “{a}” in your resume.")
        elif o == "keyword":
            kw = re.sub(r"^(?:(?:adding|add|the|a|an|keyword|key word|term|word|phrase)\s+)+", "", op["kw"].strip(" '\"“”"), flags=re.I)
            kw = re.sub(r"\s+(?:keyword|key word|term|word|phrase)$", "", kw, flags=re.I).strip(" '\"“”")
            if kw.lower() in SKILL_VOCAB or _canon_skill(kw) != kw:
                kw = _canon_skill(kw)
            placed = False
            for e in _target_units(op.get("where", ""), op["req"], content["units"], units)[:6]:
                new = _insert_keyword(e["final"], kw)
                if new and fits(e["id"], new):
                    set_line(e, new, f"Added “{kw}”")
                    placed = True
                    break
            if not placed:
                skipped.append(f"Add “{kw}”: couldn't find a natural place that fits — " +
                               ("try again when your AI model is available, or " if cfg else "connect an AI model for full rewrites, or ") +
                               "edit the line yourself above.")
    content.setdefault("requests", []).append({
        "text": request[:2000], "at": datetime.now(timezone.utc).isoformat(), "via": via, "understood_as": understood,
        "done": done, "notes": notes,
        "skipped": skipped + ai_not_done + [f"Didn't understand: “{u}”" + ("" if cfg else " — for open-ended requests like rewrites, connect an AI model "
                                                                  "(Settings → Connections, Gemini is free).") for u in unclear],
    })
    return content, content["requests"][-1]
