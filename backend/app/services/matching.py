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


# Weight presets. ATS products don't publish a formula, but they all rank mainly on skills/keyword
# match and job title, use years of experience and degree as screens, and look at soft skills least.
# The presets shift that balance for different career stages.
WEIGHT_PRESETS = {
    "typical": {"keywords": 45, "title": 15, "experience": 15, "education": 15, "soft_skills": 10},
    "entry": {"keywords": 40, "title": 10, "experience": 5, "education": 30, "soft_skills": 15},
    "experienced": {"keywords": 45, "title": 20, "experience": 25, "education": 5, "soft_skills": 5},
    "research": {"keywords": 35, "title": 10, "experience": 15, "education": 35, "soft_skills": 5},
}


def auto_preset(resume_text: str, profile: Optional[CandidateProfile] = None) -> str:
    from . import ats

    yoe = ats.resume_years(resume_text or "")
    if yoe is None and profile is not None:
        yoe = years_of_experience(profile.experience or [])
    if yoe is None or yoe < 2:
        return "entry"
    return "experienced" if yoe >= 6 else "typical"


def resolve_preset(saved: dict) -> str:
    """Saved choice; profiles saved before presets existed count as 'auto' unless the sliders were changed."""
    saved = saved or {}
    if saved.get("preset"):
        return saved["preset"]
    vals = {k: float(saved[k]) for k in WEIGHT_PRESETS["typical"] if k in saved}
    return "auto" if not vals or vals == {k: float(v) for k, v in WEIGHT_PRESETS["typical"].items() if k in vals} else "custom"


def effective_weights(saved: dict, resume_text: str = "", profile: Optional[CandidateProfile] = None) -> dict:
    """The weights actually used: a preset (auto picks one from your experience) or your custom values."""
    preset = resolve_preset(saved)
    if preset == "auto":
        preset = auto_preset(resume_text, profile)
    if preset in WEIGHT_PRESETS:
        return dict(WEIGHT_PRESETS[preset])
    w = MatchWeights(**{k: v for k, v in (saved or {}).items() if k in WEIGHT_PRESETS["typical"]}).model_dump()
    w.pop("preset", None)
    return w


def _preferred_sentence(p: dict) -> str:
    """'Meets 1 of 4 preferred qualifications; 8+ years preferred.' — companies shortlist from the preferred bar."""
    if not p or not (p.get("skills_total") or p.get("years") or p.get("degree")):
        return ""
    bits = []
    if p.get("skills_total"):
        bits.append(f"meets {p['skills_found']} of {p['skills_total']} preferred qualifications")
    if p.get("years") and p.get("meets_years") is False:
        bits.append(f"{p['years']}+ years preferred")
    if p.get("degree") and p.get("meets_degree") is False:
        bits.append({2: "a master's", 3: "a PhD"}.get(p["degree"], "a higher degree") + " preferred")
    return (bits[0][0].upper() + "; ".join(bits)[1:] + ".") if bits else ""


# role families that aren't engineering work: a "Business Development Manager" title that mentions AI software
# still isn't a role for someone targeting software engineering, unless their own target titles name it
OTHER_FUNCTION = re.compile(r"\b(business development|sales|account (executive|manager|director)|marketing|recruit(er|ing)|"
                            r"talent acquisition|customer success|partnerships?|partner manager|go-to-market|gtm|"
                            r"legal|counsel|paralegal|human resources|\bhr\b|people partner|payroll|accountant|"
                            r"procurement|buyer|copywriter|public relations|communications manager)\b", re.I)
PEOPLE_MANAGER = re.compile(r"\b(manager|head of|director|vice president|vp|chief)\b", re.I)
FIT_RANK = {"good": 0, "stretch": 1, "poor": 2}


def _candidate_level(prefs: dict, yoe: Optional[float]) -> Optional[int]:
    """Highest level the candidate is aiming at: their seniority preferences, else what their years suggest."""
    from .textutil import SENIORITY_LEVELS

    lv = [SENIORITY_LEVELS[s.lower()] for s in prefs.get("seniority") or [] if s.lower() in SENIORITY_LEVELS]
    if lv:
        return max(lv)
    if yoe is None:
        return None
    return 1 if yoe < 1 else 2 if yoe < 4 else 3 if yoe < 7 else 4


LEVEL_NAMES = {0: "intern", 1: "entry-level", 2: "mid-level", 3: "senior", 4: "staff / lead", 5: "principal"}


def level_factor(job: Job, prefs: dict, targets: list[str], yoe: Optional[float]) -> tuple[float, str]:
    """How well the role's level and kind of work fit the candidate, as a multiplier on the match score.

    Keyword overlap alone ranks a Principal or a Business Development role at the top for anyone whose resume
    shares its words; the match score has to say "not for you yet". The strongest single reason applies (no
    compounding): 1.0 = right level and kind of work."""
    from . import ats

    title = job.title or ""
    want_mgr = any(PEOPLE_MANAGER.search(t) for t in targets) or any(
        (s or "").lower() in ("manager", "head", "director", "vp", "chief") for s in prefs.get("seniority") or [])
    reasons: list[tuple[float, str]] = []
    m = OTHER_FUNCTION.search(title)
    if m and not any(OTHER_FUNCTION.search(t) for t in targets):
        reasons.append((0.5, f"a {m.group(0).lower()} role, not the kind of work you target"))
    if PEOPLE_MANAGER.search(title) and not want_mgr and not re.search(r"(?i)product manager|program manager|project manager", title):
        reasons.append((0.6, "a people-manager role; you target individual-contributor roles"))
    cand, lvl = _candidate_level(prefs, yoe), seniority_of(title)
    if cand is not None and lvl is not None and not PEOPLE_MANAGER.search(title):
        gap = lvl - cand
        if gap >= 2:
            reasons.append((0.55, f"a {LEVEL_NAMES.get(lvl, 'senior')} title, {gap} levels above you"))
        elif gap == 1:
            reasons.append((0.85, f"a {LEVEL_NAMES.get(lvl, 'senior')} title, one level above you"))
    req = required_years(job.description_text)
    implied = ats.implied_years(title) if req is None else None
    need = req if req is not None else (implied[0] if implied else None)
    if need is not None and yoe is not None:
        how = f"asks for {need}+ years" if req is not None else f"a {implied[1]} title usually means {need}+ years"
        if need > yoe + 2:
            reasons.append((0.7, f"{how}; you have about {yoe:g}"))
        elif need > yoe + 0.5:
            reasons.append((0.9, f"{how}; you have about {yoe:g}"))
    if not reasons:
        return 1.0, "Right level and kind of role for you."
    f, why = min(reasons, key=lambda r: r[0])
    return f, why[0].upper() + why[1:] + "."


def fit_verdict(job: Job, prefs: dict, targets: list[str], yoe: Optional[float], score: int, title_score: float,
                edu_status: str, flags: list[str]) -> dict:
    """Is this a role the candidate fits — not just one their keywords overlap with?
    good = apply now · stretch = possible, one thing is above where they are · poor = not their kind of role or level."""
    reasons: list[tuple[str, str]] = []  # (verdict, why)
    title = job.title or ""
    want_mgr = any(PEOPLE_MANAGER.search(t) for t in targets) or any(
        (s or "").lower() in ("manager", "head", "director", "vp", "chief") for s in prefs.get("seniority") or [])
    m = OTHER_FUNCTION.search(title)
    if m and not any(OTHER_FUNCTION.search(t) for t in targets):
        reasons.append(("poor", f"A {m.group(0).lower()} role, not the kind of role you're targeting."))
    if PEOPLE_MANAGER.search(title) and not want_mgr and not re.search(r"(?i)product manager|program manager|project manager", title):
        reasons.append(("poor", "A people-manager role; your targets are individual-contributor roles."))
    cand = _candidate_level(prefs, yoe)
    lvl = seniority_of(title)
    if cand is not None and lvl is not None and not PEOPLE_MANAGER.search(title):
        gap = lvl - cand
        names = {0: "intern", 1: "entry-level", 2: "mid-level", 3: "senior", 4: "staff / lead", 5: "principal"}
        if gap >= 2:
            reasons.append(("poor", f"{names.get(lvl, 'Senior').capitalize()} title — two or more levels above where you are."))
        elif gap == 1:
            reasons.append(("stretch", f"{names.get(lvl, 'Senior').capitalize()} title — one level above where you are."))
    req = required_years(job.description_text)
    if req is not None and yoe is not None:
        if req > yoe + 2:
            reasons.append(("poor", f"Asks for {req}+ years; you have about {yoe:g}."))
        elif req > yoe + 0.5:
            reasons.append(("stretch", f"Asks for {req}+ years; you have about {yoe:g}."))
    if targets and title_score < 0.25:
        reasons.append(("poor", "The title is far from your target titles."))
    elif targets and title_score < 0.5:
        reasons.append(("stretch", "The title only partly matches your target titles."))
    if edu_status == "below":
        reasons.append(("poor", "Needs a higher degree than yours."))
    if any(f.startswith("Work authorization: posting says it cannot sponsor") for f in flags):
        reasons.append(("poor", "Can't sponsor a visa, and you need sponsorship."))
    if score < 50:
        reasons.append(("poor", f"ATS match {score} — most of the posting's requirements aren't on your resume."))
    elif score < 65:
        reasons.append(("stretch", f"ATS match {score} — several requirements are missing from your resume."))
    verdict = max((v for v, _ in reasons), key=FIT_RANK.get, default="good")
    why = [w for v, w in reasons if v == verdict] if verdict != "good" else []
    if verdict == "good":
        bits = []
        if lvl is not None and cand is not None and lvl <= cand:
            bits.append("right level")
        if req is not None and yoe is not None and req <= yoe + 0.5:
            bits.append(f"{req}+ years asked, you have {yoe:g}")
        bits.append(f"ATS {score}")
        why = ["Good fit: " + ", ".join(bits) + "."]
    return {"verdict": verdict, "reasons": why}


def assess(job: Job, profile: CandidateProfile, resume_text: str = "", targets: Optional[list[str]] = None) -> dict:
    """ATS match of the resume against the posting + preference checks.

    `score` is the ATS-style match (see services/ats.py). Location, salary,
    seniority and sponsorship are *preference checks*: they don't change the
    ATS score but they do shape the recommendation and raise flags.
    """
    from . import ats

    prefs = profile.preferences or {}
    text = resume_text.strip() or candidate_evidence_text(profile)
    jd = f"{job.title}\n{job.description_text}".lower()
    degrees = [" ".join(x for x in (e.get("degree", ""), e.get("field", "")) if x) for e in (profile.education or [])]
    weights = effective_weights(profile.match_weights or {}, text, profile)
    a = ats.score(text, job.title, job.description_text or "", job.company, weights,
                  targets if targets is not None else (prefs.get("target_titles") or []),
                  degrees=[d for d in degrees if d])
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
    edu = a["education"]
    if edu["status"] == "below":
        flags.append("Education: " + edu["note"])
    if len(job.description_text or "") < 200:
        flags.append("Only a short job summary is available so far — JobPilot fetches the full description when you open the job.")
    if job.is_simulated:
        flags.append("SIMULATED listing (demo data) — not a real job.")

    # the match score includes level fit: a role two levels above you can't rank as a 100
    tgt = targets if targets is not None else (prefs.get("target_titles") or [])
    ats_score = score
    factor, level_note = level_factor(job, prefs, tgt, yoe)
    score = round(ats_score * factor)
    rec = "apply" if score >= 70 else "review" if score >= 50 else "skip"
    hard = any(f.startswith(("Work authorization:", "Contains excluded", "Listing is no longer", "Location:")) for f in flags)
    if hard and rec == "apply":
        rec = "review"
    if edu["status"] == "below":
        rec = "skip"  # e.g. a PhD-only role for a master's graduate: don't suggest it
    fit = fit_verdict(job, prefs, tgt, yoe, ats_score, (a["breakdown"].get("title") or {}).get("score", 1.0), edu["status"], flags)
    if fit["verdict"] == "poor":
        rec = "skip"  # not the candidate's kind of role or level: don't suggest it, whatever the keyword overlap
    elif fit["verdict"] == "stretch" and rec == "apply":
        rec = "review"

    bd = a["breakdown"]
    strengths = [k.replace("_", " ") for k, v in bd.items() if v["score"] >= 0.75]
    weak = [k.replace("_", " ") for k, v in bd.items() if v["score"] < 0.4]
    explanation = (
        (f"Match {score}/100 = ATS {ats_score} × level fit {factor:g} ({level_note.rstrip('.')}). " if factor < 1
         else f"ATS match {score}/100. ")
        + (f"Strong on {', '.join(strengths)}. " if strengths else "")
        + (f"Weak on {', '.join(weak)}. " if weak else "")
        + (f"Missing required keywords: {', '.join(a['missing_required'][:8])}. " if a["missing_required"] else "")
        + _preferred_sentence(a.get("preferred") or {})
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
    breakdown["_education"] = edu
    breakdown["_preferred"] = a.get("preferred")
    breakdown["_experience_bars"] = a.get("experience_bars")
    breakdown["_fit"] = fit
    breakdown["_level"] = {"factor": factor, "ats_score": ats_score, "note": level_note}

    return {
        "score": score,
        "recommendation": rec,
        "breakdown": breakdown,
        "matched_skills": matched,
        "missing_skills": missing,
        "flags": flags,
        "explanation": explanation,
        "weights": weights,
        "edu_status": edu["status"],
        "fit": fit["verdict"],
        "relevant_experience": relevant[:6],
        "years_experience": yoe,
    }


# Bump when scoring changes so existing jobs are re-scored in the background (scheduler → score_unscored).
# 2: scored against preferred qualifications (preferred years/degree/skills), any-of lists, example lists.
# 3: fit verdict (level, years, kind of role, title) — poor fits become "skip" and aren't alerted.
# 4: level fit multiplies the match score; years implied by Senior/Staff/Principal titles; thin postings scored cautiously.
# 5: "MS + 5 OR BS + 7 years" in one sentence read as two paths; list items without leading "with"/"in".
SCORING_VERSION = 5


def load_tracks(db: Session, user_id: int) -> list:
    """The user's role tracks as scoring views: each with its own resume text (the primary resume if none is set)."""
    from ..models import Resume, RoleTrack
    from .roles import BY_KEY, TrackView

    rows = db.query(RoleTrack).filter_by(user_id=user_id).order_by(RoleTrack.position, RoleTrack.id).all()
    if not rows:
        return []
    primary = db.query(Resume).filter_by(user_id=user_id, is_primary=True).one_or_none()
    out = []
    for t in rows:
        r = db.get(Resume, t.resume_id) if t.resume_id else None
        fam = BY_KEY.get(t.family)
        titles = [x for x in (t.target_titles or []) if x.strip()] or (list(fam.titles[:5]) if fam else [t.name])
        out.append(TrackView(id=t.id, name=t.name, family=t.family, titles=titles,
                             resume_text=(r or primary).text if (r or primary) else ""))
    return out


def assess_tracks(job: Job, profile: CandidateProfile, tracks: list) -> tuple[dict, Optional[int]]:
    """Score a job against the role track(s) it belongs to and keep the best.

    Only tracks of the job's role family are scored (an ML posting against the ML resume), unless you picked a
    track for this job yourself; a title that fits no track is scored against every track and goes to the closest.
    """
    from .roles import candidate_tracks

    chosen = [t for t in tracks if t.id == job.resume_track_id]
    cands, reason = (chosen, "chosen") if chosen else candidate_tracks(tracks, job.title)
    results = [(t, assess(job, profile, t.resume_text, t.titles)) for t in cands]
    # the track where you FIT best wins (a good-fit ML role beats a higher keyword score on a stretch track)
    best_t, best = max(results, key=lambda r: (-FIT_RANK.get(r[1]["fit"], 1), r[1]["score"]))
    best["breakdown"]["_track"] = {"id": best_t.id, "name": best_t.name, "family": best_t.family, "reason": reason,
                                   "scores": [{"id": t.id, "name": t.name, "score": a["score"]} for t, a in results]}
    return best, best_t.id


def score_job(db: Session, job: Job, profile: Optional[CandidateProfile] = None,
              tracks: Optional[list] = None) -> Optional[MatchAssessment]:
    profile = profile or db.query(CandidateProfile).filter_by(user_id=job.user_id).one_or_none()
    if profile is None:
        return None
    from ..models import Resume

    tracks = load_tracks(db, job.user_id) if tracks is None else tracks
    track_id = None
    if tracks:
        result, track_id = assess_tracks(job, profile, tracks)
    else:
        resume = db.query(Resume).filter_by(user_id=job.user_id, is_primary=True).one_or_none()
        result = assess(job, profile, resume.text if resume else "")
    result.pop("relevant_experience")
    result.pop("years_experience")
    m = MatchAssessment(user_id=job.user_id, job_id=job.id, track_id=track_id, scoring_version=SCORING_VERSION, **result)
    db.add(m)
    db.flush()
    # keep only the latest assessment per job: older ones are never read, and every re-score used to add a row
    # (25,000 rows for 9,400 jobs), slowing every page and filling the database
    db.query(MatchAssessment).filter(MatchAssessment.job_id == job.id, MatchAssessment.id != m.id).delete(synchronize_session=False)
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
    tracks = load_tracks(db, user_id)
    n = 0
    for job in q.all():
        score_job(db, job, profile, tracks)
        n += 1
    db.commit()
    return n


def latest_assessment(db: Session, job_id: int) -> Optional[MatchAssessment]:
    return (
        db.query(MatchAssessment).filter_by(job_id=job_id).order_by(MatchAssessment.id.desc()).first()
    )
