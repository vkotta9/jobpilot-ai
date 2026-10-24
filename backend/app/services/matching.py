"""Job Matching Agent — transparent, deterministic, configurable scoring.

score = Σ weight_i × component_i / Σ weight_i   (each component in [0, 1])

Components: skills, title, seniority, location, compensation. Unknown data
(e.g. no salary posted) scores a neutral 0.5 and is reported as unknown rather
than guessed. Work-authorization conflicts are surfaced as a flag that caps the
recommendation; they are a factual eligibility requirement, not a penalty.
Only job-relevant signals are used. Protected characteristics (age, gender,
race, religion, disability, etc.) are never inputs.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from ..models import CandidateProfile, Job, MatchAssessment
from ..schemas import MatchWeights
from .textutil import (
    canon_skill,
    contains_term,
    find_skills,
    normalize,
    required_years,
    seniority_of,
    tokens,
    years_of_experience,
)

NO_SPONSOR_RE = re.compile(
    r"(unable|not able|cannot|can't|will not|won't|do not|does not|don't|not)\s+(to\s+)?(provide\s+|offer\s+)?sponsor"
    r"|no\s+(visa\s+)?sponsorship|without\s+(visa\s+)?sponsorship|sponsorship\s+(is\s+)?not\s+available",
    re.I,
)


def candidate_evidence_text(p: CandidateProfile, resume_text: str = "") -> str:
    parts = [p.headline, p.summary, " ".join(p.skills or []), resume_text]
    for e in p.experience or []:
        parts += [e.get("title", ""), " ".join(e.get("bullets", []))]
    for pr in p.projects or []:
        parts += [pr.get("name", ""), pr.get("description", "")]
    parts += list(p.certifications or [])
    return "\n".join(x for x in parts if x).lower()


def _title_score(job_title: str, targets: list[str]) -> tuple[float, str]:
    if not targets:
        return 0.5, "No target titles set (neutral)."
    jt = set(tokens(job_title)) - {"senior", "sr", "junior", "jr", "staff", "lead", "principal", "ii", "iii"}
    best, best_t = 0.0, ""
    for t in targets:
        tt = set(tokens(t)) - {"senior", "sr", "junior", "jr", "staff", "lead", "principal"}
        if not tt:
            continue
        overlap = len(jt & tt) / len(tt)
        if normalize(t) in normalize(job_title):
            overlap = 1.0
        if overlap > best:
            best, best_t = overlap, t
    if best == 0:
        return 0.0, "Title does not match any target title."
    return round(best, 2), f"Closest target title: “{best_t}” ({int(best * 100)}% term overlap)."


def _seniority_score(job: Job, prefs: dict, yoe: Optional[float]) -> tuple[float, str, Optional[str]]:
    from .textutil import SENIORITY_LEVELS

    notes = []
    flag = None
    job_lvl = seniority_of(job.title)
    pref_lvls = [SENIORITY_LEVELS[s.lower()] for s in prefs.get("seniority") or [] if s.lower() in SENIORITY_LEVELS]
    level_score = 0.5
    if job_lvl is not None and pref_lvls:
        dist = min(abs(job_lvl - p) for p in pref_lvls)
        level_score = {0: 1.0, 1: 0.6}.get(dist, 0.1)
        notes.append(f"Title level {'matches' if dist == 0 else 'is ' + str(dist) + ' step(s) from'} your preference.")
    elif job_lvl is None:
        notes.append("Seniority not stated in title.")
    req = required_years(job.description_text)
    yrs_score = None
    if req is not None and yoe is not None:
        yrs_score = 1.0 if yoe >= req else max(0.0, 1 - (req - yoe) / max(req, 1))
        notes.append(f"Asks for ~{req}+ years; your dated experience totals {yoe} years.")
        if yoe + 2 < req:
            flag = f"Experience gap: posting asks for {req}+ years, profile shows {yoe}."
    elif req is not None:
        notes.append(f"Asks for ~{req}+ years; add dates to your experience to compare.")
    score = level_score if yrs_score is None else (level_score + yrs_score) / 2
    return round(score, 2), " ".join(notes), flag


def _location_score(job: Job, prefs: dict) -> tuple[float, str]:
    wp = set(prefs.get("workplace") or [])
    locs = [normalize(l) for l in prefs.get("locations") or [] if l.strip()]
    jl = normalize(job.location)
    if job.remote_type == "remote":
        if not wp or "remote" in wp:
            return 1.0, "Remote role, matches your workplace preference."
        return 0.6, "Remote role (you prefer " + "/".join(sorted(wp)) + ")."
    loc_hit = any(l and (l in jl or jl.split(",")[0].strip() in l) for l in locs) if jl else False
    if job.remote_type in ("hybrid", "onsite"):
        type_ok = not wp or job.remote_type in wp
        if loc_hit and type_ok:
            return 1.0, f"{job.remote_type.title()} in a preferred location."
        if loc_hit:
            return 0.6, f"Preferred location, but {job.remote_type} (you prefer {'/'.join(sorted(wp))})."
        if not locs:
            return (0.6 if type_ok else 0.3), "No preferred locations set."
        return 0.1, f"{job.remote_type.title()} role outside your preferred locations."
    if not jl:
        return 0.5, "Location not stated (neutral)."
    return (1.0 if loc_hit else 0.3), ("Preferred location." if loc_hit else "Outside preferred locations.")


def _comp_score(job: Job, prefs: dict) -> tuple[float, str]:
    want_min = prefs.get("salary_min")
    if job.salary_min is None and job.salary_max is None:
        return 0.5, "Salary not posted (neutral, unknown)."
    if not want_min:
        return 0.5, "No salary preference set (neutral)."
    interval = (job.salary_interval or "").lower()
    if interval and "year" not in interval and "annual" not in interval:
        return 0.5, f"Salary given {interval}; not compared to annual target."
    top = job.salary_max or job.salary_min
    if top >= want_min:
        return 1.0, f"Posted range reaches your minimum ({int(want_min):,})."
    return round(max(0.0, top / want_min) ** 3, 2), f"Posted max {int(top):,} is below your minimum {int(want_min):,}."


def assess(job: Job, profile: CandidateProfile, resume_text: str = "") -> dict:
    """ATS match of the resume against the posting + preference checks.

    `score` is the ATS-style match (see services/ats.py). Location, salary,
    seniority and sponsorship are *preference checks*: they don't change the
    ATS score but they do shape the recommendation and raise flags.
    """
    from . import ats

    prefs = profile.preferences or {}
    weights = MatchWeights(**(profile.match_weights or {})).model_dump()
    text = resume_text.strip() or candidate_evidence_text(profile)
    jd = f"{job.title}\n{job.description_text}".lower()
    a = ats.score(text, job.title, job.description_text or "", job.company, weights, prefs.get("target_titles") or [])
    score = a["score"]
    matched, missing = a["matched"], a["missing"]

    yoe = ats.resume_years(text) or years_of_experience(profile.experience or [])
    sen_score, sen_note, sen_flag = _seniority_score(job, prefs, yoe)
    loc_score, loc_note = _location_score(job, prefs)
    comp_score, comp_note = _comp_score(job, prefs)
    preferences = {
        "location": {"score": loc_score, "note": loc_note},
        "compensation": {"score": comp_score, "note": comp_note},
        "seniority": {"score": sen_score, "note": sen_note},
    }

    flags: list[str] = []
    auth = profile.work_authorization or {}
    if NO_SPONSOR_RE.search(job.description_text or ""):
        if auth.get("requires_sponsorship") is True:
            flags.append("Work authorization: posting says it cannot sponsor; your profile says you need sponsorship.")
        elif auth.get("requires_sponsorship") is None:
            flags.append("Posting says no sponsorship. Set your sponsorship need in your profile to check eligibility.")
    if sen_flag:
        flags.append(sen_flag)
    excl = [k for k in prefs.get("exclude_keywords") or [] if k and contains_term(jd, k.lower())]
    if excl:
        flags.append("Contains excluded keyword(s): " + ", ".join(excl))
    if loc_score <= 0.1:
        flags.append("Location: " + loc_note)
    if job.listing_status != "active":
        flags.append("Listing is no longer active on its source.")
    if len(job.description_text or "") < 600:
        flags.append("Only a short job summary is available — open the posting and paste the full description for an accurate score.")
    if job.is_simulated:
        flags.append("SIMULATED listing (demo data) — not a real job.")

    rec = "apply" if score >= 70 else "review" if score >= 50 else "skip"
    hard = any(f.startswith(("Work authorization:", "Contains excluded", "Listing is no longer", "Location:")) for f in flags)
    if hard and rec == "apply":
        rec = "review"

    bd = a["breakdown"]
    strengths = [k.replace("_", " ") for k, v in bd.items() if v["score"] >= 0.75]
    weak = [k.replace("_", " ") for k, v in bd.items() if v["score"] < 0.4]
    explanation = (
        f"ATS match {score}/100. "
        + (f"Strong on {', '.join(strengths)}. " if strengths else "")
        + (f"Weak on {', '.join(weak)}. " if weak else "")
        + (f"Missing required keywords: {', '.join(a['missing_required'][:8])}." if a["missing_required"] else "")
    ).strip()

    relevant = []
    for e in profile.experience or []:
        for b in e.get("bullets", []):
            hits = [s for s in matched if contains_term(b.lower(), s)]
            if hits:
                relevant.append({"company": e.get("company", ""), "title": e.get("title", ""), "bullet": b, "skills": hits})
    relevant.sort(key=lambda r: -len(r["skills"]))
    breakdown = dict(bd)
    breakdown["_preferences"] = preferences
    breakdown["_keywords"] = a["keywords"]
    breakdown["_soft"] = {"matched": a["soft_matched"], "missing": a["soft_missing"]}
    breakdown["_missing_required"] = a["missing_required"]
    breakdown["_resume_source"] = "uploaded resume" if resume_text.strip() else "profile"

    return {
        "score": score,
        "recommendation": rec,
        "breakdown": breakdown,
        "matched_skills": matched,
        "missing_skills": missing,
        "flags": flags,
        "explanation": explanation,
        "weights": weights,
        "relevant_experience": relevant[:6],
        "years_experience": yoe,
    }


def score_job(db: Session, job: Job, profile: Optional[CandidateProfile] = None) -> Optional[MatchAssessment]:
    profile = profile or db.query(CandidateProfile).filter_by(user_id=job.user_id).one_or_none()
    if profile is None:
        return None
    from ..models import Resume

    resume = db.query(Resume).filter_by(user_id=job.user_id, is_primary=True).one_or_none()
    result = assess(job, profile, resume.text if resume else "")
    result.pop("relevant_experience")
    result.pop("years_experience")
    m = MatchAssessment(user_id=job.user_id, job_id=job.id, **result)
    db.add(m)
    db.flush()
    return m


def score_jobs(db: Session, user_id: int, job_ids: Optional[Iterable[int]] = None) -> int:
    profile = db.query(CandidateProfile).filter_by(user_id=user_id).one_or_none()
    if profile is None:
        return 0
    q = db.query(Job).filter(Job.user_id == user_id)
    if job_ids is not None:
        ids = list(job_ids)
        if not ids:
            return 0
        q = q.filter(Job.id.in_(ids))
    n = 0
    for job in q.all():
        score_job(db, job, profile)
        n += 1
    db.commit()
    return n


def latest_assessment(db: Session, job_id: int) -> Optional[MatchAssessment]:
    return (
        db.query(MatchAssessment).filter_by(job_id=job_id).order_by(MatchAssessment.id.desc()).first()
    )
