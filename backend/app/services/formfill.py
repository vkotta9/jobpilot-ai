"""What the browser extension puts into application forms.

* Name parts and postal address come from Profile → Application details when filled in. Otherwise the name is
  split as first word / middle words / last word, and the address is left empty (never guessed from "USA").
* The free-text location ("Buffalo, NY", "USA", "Austin, Texas, United States") is parsed into city / state /
  country only where the parts are recognisable.
* Questions the extension's own rules can't answer are answered here from the profile, approved screening
  answers and the resume — with the AI when connected, strictly from those facts, and "" when unknown.
"""
from __future__ import annotations

import re
from typing import Optional

from . import llm

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
}
_STATE_BY_NAME = {v.lower(): k for k, v in US_STATES.items()}
COUNTRIES = {
    "usa": "United States", "us": "United States", "u.s.": "United States", "u.s.a.": "United States", "united states": "United States",
    "united states of america": "United States", "america": "United States", "india": "India", "canada": "Canada",
    "uk": "United Kingdom", "united kingdom": "United Kingdom", "england": "United Kingdom", "germany": "Germany",
    "ireland": "Ireland", "australia": "Australia", "singapore": "Singapore", "netherlands": "Netherlands",
    "france": "France", "spain": "Spain", "mexico": "Mexico", "brazil": "Brazil", "japan": "Japan",
}


def country_name(s: str) -> str:
    return COUNTRIES.get((s or "").strip().lower().rstrip("."), "")


def state_name(s: str) -> str:
    t = (s or "").strip()
    if t.upper() in US_STATES:
        return US_STATES[t.upper()]
    return US_STATES[_STATE_BY_NAME[t.lower()]] if t.lower() in _STATE_BY_NAME else ""


def parse_location(loc: str) -> dict:
    """'Buffalo, NY' → city Buffalo, state New York, country United States. 'USA' → country only."""
    parts = [p.strip() for p in re.split(r",|\s+-\s+", loc or "") if p.strip()]
    parts = [p for p in parts if not re.fullmatch(r"(?i)remote|hybrid|on-?site|anywhere", p)]
    city = state = country = ""
    for p in reversed(parts):
        if not country and country_name(p):
            country = country_name(p)
        elif not state and state_name(re.sub(r"\s+\d{5}(-\d{4})?$", "", p)):
            state = state_name(re.sub(r"\s+\d{5}(-\d{4})?$", "", p))
        elif not city and not country_name(p) and (state or not state_name(p)) and re.search(r"[A-Za-z]", p):
            city = p
    if state and not country and state in US_STATES.values():
        country = "United States"
    return {"city": city, "state": state, "state_code": _STATE_BY_NAME.get(state.lower(), ""), "country": country}


def name_parts(full: str, details: dict) -> dict:
    """The user's own first / middle / last name if set in Profile → Application details;
    otherwise first word / middle words / last word ("Vijay Kumar Kotta" → Vijay / Kumar / Kotta)."""
    tokens = (full or "").split()
    mine = bool(details.get("first_name") or details.get("last_name"))
    if mine:
        first, middle, last = details.get("first_name", ""), details.get("middle_name", ""), details.get("last_name", "")
    else:
        first = tokens[0] if tokens else ""
        last = tokens[-1] if len(tokens) > 1 else ""
        middle = " ".join(tokens[1:-1])
    return {"first_name": first, "middle_name": middle, "last_name": last,
            "preferred_name": details.get("preferred_name") or first,
            "full_name": full or " ".join(x for x in (first, middle, last) if x), "name_set_by_user": mine}


def address(details: dict, loc: dict) -> dict:
    """Postal address: only what the user entered. City/state/country fall back to the parsed location."""
    st = details.get("state") or loc["state"]
    return {"address_line1": details.get("address_line1", ""), "address_line2": details.get("address_line2", ""),
            "city": details.get("city") or loc["city"], "state": state_name(st) or st,
            "state_code": _STATE_BY_NAME.get((state_name(st) or st).lower(), ""),
            "postal_code": details.get("postal_code", ""),
            "country": country_name(details.get("country", "")) or details.get("country", "") or loc["country"]}


# ---------------------------------------------------------------- AI answers for the remaining questions
NEVER = re.compile(r"gender|\bsex\b|race|ethnic|hispanic|latino|veteran|disabilit|pronoun|sexual orientation|transgender|"
                   r"date of birth|birth ?date|\bage\b|social security|\bssn\b|religion|marital|captcha|password|signature|"
                   r"i agree|consent|terms|privacy|acknowledg|certify|attest|criminal|convict|felony|background check", re.I)

TASK = """Fill in a job application form for the candidate. For each question, answer ONLY from candidate_facts
(their verified profile, saved answers and resume). Rules:
- If the facts don't clearly answer it, return answer="" (the candidate will answer it). Never guess, never invent
  employers, dates, numbers, salary, addresses, IDs or links.
- For questions with options, answer must be exactly one of the given options (copy it), or "".
- Yes/no questions: answer only if the facts say so (e.g. work authorization, sponsorship, relocation).
- Short fields (name, city, phone, title, school, years): the bare value, no sentence.
- Long questions (why this role, describe experience): 2-4 sentences in first person, from the resume facts only.
- Never answer demographic/EEO, legal attestations, consents, criminal-history or background questions: return "".
Return every question id."""

SCHEMA = llm.strict_schema({"answers": {"type": "array", "items": llm.strict_schema(
    {"id": {"type": "string"}, "answer": {"type": "string"}, "basis": {"type": "string"}})}})


def facts_text(P: dict, W: dict, details: dict, answers: list[dict], resume_text: str) -> str:
    lines = [f"{k}: {v}" for k, v in P.items() if v not in (None, "", []) and k != "name_set_by_user"]
    if W.get("authorized_countries"):
        lines.append("authorized to work in: " + ", ".join(W["authorized_countries"]))
    if W.get("requires_sponsorship") is not None:
        lines.append("requires visa sponsorship now or in future: " + ("yes" if W["requires_sponsorship"] else "no"))
    for k in ("willing_to_relocate", "earliest_start", "salary_expectation", "how_heard"):
        v = details.get(k)
        if v not in (None, ""):
            lines.append(f"{k.replace('_', ' ')}: {'yes' if v is True else 'no' if v is False else v}")
    for a in answers[:40]:
        lines.append(f"saved answer — Q: {a['question'][:200]} A: {a['answer'][:600]}")
    return "\n".join(lines) + "\n\nResume:\n" + (resume_text or "")[:7000]


def answer_questions(cfg, job: dict, questions: list[dict], facts: str) -> list[dict]:
    qs = [q for q in questions if not NEVER.search(q.get("label", ""))]
    if not qs or cfg is None:
        return []
    body = "\n".join(f'- id={q["id"]} kind={q.get("kind", "text")}: {q["label"][:300]}'
                     + (f'\n  options: {" | ".join(o[:100] for o in q.get("options", [])[:40])}' if q.get("options") else "")
                     for q in qs[:40])
    payload = (f"<target_job>{job.get('title', '')} at {job.get('company', '')}</target_job>\n"
               f"<candidate_facts>\n{facts}\n</candidate_facts>\n"
               + llm.untrusted("form_questions", body, 12000))
    out = llm.complete_json(TASK, payload, SCHEMA, cfg=cfg, name="form_answers", max_attempts=1, busy_budget_s=20)
    by_id = {q["id"]: q for q in qs}
    res = []
    for a in out.get("answers", []):
        q = by_id.get(a.get("id"))
        ans = (a.get("answer") or "").strip()
        if not q or not ans:
            continue
        if q.get("options"):
            match = next((o for o in q["options"] if o.strip().lower() == ans.lower()), None)
            if match is None:
                continue  # not one of the choices: leave it for the user
            ans = match
        res.append({"id": q["id"], "answer": ans[:4000], "basis": (a.get("basis") or "")[:200]})
    return res
