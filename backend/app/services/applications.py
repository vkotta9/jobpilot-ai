"""Application Agent + Tracker Agent: deterministic state machine and approval gate.

Rules enforced here (not in the UI, so they cannot be bypassed by API calls):
* An application can only reach `applied` through `record_submission`, which
  requires (a) a current approval and (b) explicit confirmation.
* Approval requires a resume — an approved tailored version for this job, or
  otherwise the user's own uploaded (master) resume as-is — an approved cover
  letter (if one exists), no unresolved [[ADD: ...]] placeholders and no
  screening answers still needing the user's input. Tailoring is optional.
* Approval is bound to a hash of the exact materials; editing anything after
  approval invalidates it.
* A job can only have one application (unique constraint) and one submission.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import (
    Application,
    ApplicationEvent,
    CandidateProfile,
    Document,
    FollowUpTask,
    Job,
    ScreeningAnswer,
    UserSettings,
    utcnow,
)
from ..security import audit
from .tailoring import unresolved_placeholders
from .textutil import sha256

# manual transitions the user may make from the tracker
MANUAL_TRANSITIONS: dict[str, set[str]] = {
    "shortlisted": {"preparing", "withdrawn", "rejected"},
    "preparing": {"shortlisted", "withdrawn"},
    "awaiting_approval": {"preparing", "withdrawn"},
    "applied": {"assessment", "interview", "offer", "rejected", "withdrawn"},
    "assessment": {"interview", "offer", "rejected", "withdrawn"},
    "interview": {"assessment", "interview", "offer", "rejected", "withdrawn"},
    "offer": {"withdrawn", "rejected"},
    "rejected": set(),
    "withdrawn": {"shortlisted"},
}


def event(db: Session, app: Application, kind: str, frm: str = "", to: str = "", detail: str = "", verified: bool = False) -> None:
    db.add(ApplicationEvent(user_id=app.user_id, application_id=app.id, kind=kind, from_status=frm,
                            to_status=to, detail=detail, verified=verified))


def get_or_create(db: Session, job: Job) -> Application:
    app = db.query(Application).filter_by(user_id=job.user_id, job_id=job.id).one_or_none()
    if app:
        return app
    app = Application(user_id=job.user_id, job_id=job.id, status="shortlisted")
    db.add(app)
    db.flush()
    event(db, app, "status", "discovered", "shortlisted", "Shortlisted")
    audit(db, job.user_id, "application.create", "application", app.id, job_id=job.id)
    return app


def change_status(db: Session, app: Application, new: str, detail: str = "") -> Application:
    allowed = MANUAL_TRANSITIONS.get(app.status, set())
    if new == "applied":
        raise HTTPException(400, "Use 'Record submission' to mark an application as applied (requires approval).")
    if new == "awaiting_approval":
        raise HTTPException(400, "Use 'Request approval' — it validates the package first.")
    if new not in allowed:
        raise HTTPException(400, f"Cannot move from '{app.status}' to '{new}'. Allowed: {', '.join(sorted(allowed)) or 'none'}.")
    old = app.status
    app.status = new
    if new in ("preparing", "shortlisted", "withdrawn") and old == "awaiting_approval":
        invalidate_approval(db, app, "Moved back from awaiting approval")
    event(db, app, "status", old, new, detail or "Manual update", verified=False)
    audit(db, app.user_id, "application.status", "application", app.id, frm=old, to=new)
    if new == "interview":
        _ensure_task(db, app, "interview_follow_up", "Send thank-you / follow up after interview", days=2)
    return app


def _ensure_task(db: Session, app: Application, kind: str, title: str, days: int) -> Optional[FollowUpTask]:
    st = db.get(UserSettings, app.user_id)
    if st and (st.workflows or {}).get("follow_up_tasks") is False:
        return None
    key = f"app:{app.id}:{kind}:{app.status}"
    if db.query(FollowUpTask).filter_by(user_id=app.user_id, dedupe_key=key).first():
        return None
    t = FollowUpTask(user_id=app.user_id, application_id=app.id, kind=kind, dedupe_key=key,
                     title=f"{title} — {app.job.title} @ {app.job.company}", due_at=utcnow() + timedelta(days=days))
    db.add(t)
    if kind == "application_follow_up":
        app.follow_up_at = t.due_at
    return t


def latest_doc(db: Session, job_id: int, kind: str) -> Optional[Document]:
    return db.query(Document).filter_by(job_id=job_id, kind=kind).order_by(Document.version.desc()).first()


def approved_tailored(db: Session, job_id: int) -> Optional[Document]:
    return (db.query(Document).filter_by(job_id=job_id, kind="resume", status="approved")
            .order_by(Document.version.desc()).first())


def master_resume(db: Session, user_id: int):
    from ..models import Resume

    return db.query(Resume).filter_by(user_id=user_id, is_primary=True).one_or_none()


def resume_choice(db: Session, app: Application) -> dict:
    """Which resume this application uses: the approved tailored version, else the master resume."""
    doc = approved_tailored(db, app.job_id)
    if doc is not None:
        return {"type": "tailored", "doc_id": doc.id, "version": doc.version}
    r = master_resume(db, app.user_id)
    if r is not None:
        return {"type": "master", "resume_id": r.id, "filename": r.original_filename}
    return {"type": "none"}


def package_hash(db: Session, app: Application) -> str:
    resume = db.get(Document, app.resume_doc_id) if app.resume_doc_id else None
    master = master_resume(db, app.user_id) if resume is None else None
    letter = db.get(Document, app.cover_letter_doc_id) if app.cover_letter_doc_id else None
    answers = db.query(ScreeningAnswer).filter_by(application_id=app.id).order_by(ScreeningAnswer.id).all()
    return sha256(
        repr(resume.content) if resume else "", resume.status if resume else "",
        f"master:{master.id}:{master.sha256}" if master else "",
        repr(letter.content) if letter else "", letter.status if letter else "",
        *[f"{a.id}:{a.answer}:{a.status}" for a in answers],
    )


def package_problems(db: Session, app: Application) -> list[str]:
    problems = []
    resume = approved_tailored(db, app.job_id)  # a tailored resume is optional; drafts don't block approval
    letter = latest_doc(db, app.job_id, "cover_letter")
    if resume is None and master_resume(db, app.user_id) is None:
        problems.append("Upload your resume in the Resume library (or tailor one for this job).")
    if letter and letter.status != "approved":
        problems.append("Approve the latest cover letter (or delete it).")
    for d in (resume, letter):
        if d and unresolved_placeholders(d.content):
            problems.append(f"Fill the [[ADD: …]] placeholder(s) in your {d.kind.replace('_', ' ')}.")
    pending = db.query(ScreeningAnswer).filter(ScreeningAnswer.application_id == app.id,
                                               ScreeningAnswer.status != "approved").count()
    if pending:
        problems.append(f"{pending} screening answer(s) need your input or approval.")
    if app.job.listing_status != "active":
        problems.append("This listing is no longer active on its source.")
    return problems


def request_approval(db: Session, app: Application) -> dict:
    if app.status in ("applied", "assessment", "interview", "offer", "rejected"):
        raise HTTPException(400, "This application has already been submitted or closed.")
    resume = approved_tailored(db, app.job_id)
    app.resume_doc_id = resume.id if resume else None  # None = the master resume
    letter = latest_doc(db, app.job_id, "cover_letter")
    app.cover_letter_doc_id = letter.id if letter else None
    problems = package_problems(db, app)
    if problems:
        if app.status in ("shortlisted",):
            app.status = "preparing"
        return {"ok": False, "problems": problems, "status": app.status}
    old = app.status
    app.status = "awaiting_approval"
    event(db, app, "status", old, "awaiting_approval", "Package validated, awaiting your approval")
    return {"ok": True, "problems": [], "status": app.status}


def approve(db: Session, app: Application, confirm: bool) -> dict:
    if not confirm:
        raise HTTPException(400, "Explicit confirmation is required to approve an application package.")
    if app.status != "awaiting_approval":
        raise HTTPException(400, "Request approval first so the package can be validated.")
    problems = package_problems(db, app)
    if problems:
        raise HTTPException(400, "Package is not ready: " + " ".join(problems))
    app.approved_at = utcnow()
    app.approved_package_hash = package_hash(db, app)
    event(db, app, "approved", "", "", "You approved this application package")
    audit(db, app.user_id, "application.approve", "application", app.id)
    return {"ok": True, "approved_at": app.approved_at.isoformat() + "Z"}


def invalidate_approval(db: Session, app: Application, reason: str) -> None:
    if app.approved_at:
        app.approved_at = None
        app.approved_package_hash = ""
        event(db, app, "approval_revoked", "", "", reason)
        if app.status == "awaiting_approval":
            app.status = "preparing"


def approval_is_current(db: Session, app: Application) -> bool:
    return bool(app.approved_at and app.approved_package_hash and app.approved_package_hash == package_hash(db, app))


def record_submission(db: Session, app: Application, confirm: bool, method: str, detail: str) -> dict:
    """Record that the user submitted the application on the official site.

    JobPilot never auto-submits in this MVP. `submission_verified` is True only
    when the user pastes a confirmation (email text / confirmation number);
    otherwise the submission is stored as user-reported.
    """
    if app.submitted_at:
        raise HTTPException(409, "This application was already recorded as submitted (duplicate prevented).")
    if not confirm:
        raise HTTPException(400, "Confirm that you submitted this application yourself on the official site.")
    if not approval_is_current(db, app):
        raise HTTPException(400, "The application package is not approved (or changed since approval). Approve it first.")
    old = app.status
    app.status = "applied"
    app.submitted_at = utcnow()
    app.submission_method = method
    app.confirmation_detail = detail.strip()
    app.submission_verified = bool(re.search(r"\w{4,}", detail or ""))
    event(db, app, "submitted", old, "applied",
          "Confirmation: " + detail.strip() if detail.strip() else "User reported submission (no confirmation provided)",
          verified=app.submission_verified)
    audit(db, app.user_id, "application.submitted", "application", app.id, method=method, verified=app.submission_verified)
    try:  # start your interview prep plan right away (rules only: fast, no AI call)
        from ..api.prep import build_for

        build_for(db, app)
    except Exception:  # noqa: BLE001 - never block recording a submission
        pass
    days = (db.get(UserSettings, app.user_id).follow_up_days if db.get(UserSettings, app.user_id) else 7)
    _ensure_task(db, app, "application_follow_up", "Follow up on application", days=days)
    return {"ok": True, "verified": app.submission_verified}


# ---------------------------------------------------------------- screening questions

SENSITIVE = {
    "work_authorization": re.compile(r"(legally )?authori[sz]ed to work|work authori[sz]ation|eligible to work|right to work", re.I),
    "sponsorship": re.compile(r"sponsor", re.I),
    "salary": re.compile(r"salary|compensation|pay expectation|desired pay|expected pay", re.I),
    "criminal": re.compile(r"convict|criminal|felony|background check", re.I),
    "demographic": re.compile(r"gender|race|ethnic|veteran|disabilit|sexual orientation|pronoun|age\b|date of birth", re.I),
    "relocation": re.compile(r"relocat", re.I),
    "start_date": re.compile(r"start date|notice period|when can you start|available to start", re.I),
    "links": re.compile(r"linkedin|github|portfolio|website", re.I),
    "years": re.compile(r"how many years|years of (professional )?experience", re.I),
}


def question_key(q: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", q.lower()).strip()[:300]


def categorize(q: str) -> str:
    for cat, rx in SENSITIVE.items():
        if rx.search(q):
            return cat
    return "general"


def draft_answer(db: Session, profile: CandidateProfile, q: str) -> tuple[str, str, str, str]:
    """Return (answer, status, category, source). Never guesses personal facts."""
    cat = categorize(q)
    saved = (
        db.query(ScreeningAnswer)
        .filter(ScreeningAnswer.user_id == profile.user_id, ScreeningAnswer.question_key == question_key(q),
                ScreeningAnswer.reusable.is_(True), ScreeningAnswer.status == "approved")
        .order_by(ScreeningAnswer.id.desc()).first()
    )
    if saved:
        return saved.answer, "draft", cat, "Reused your saved answer"
    auth = profile.work_authorization or {}
    if cat == "sponsorship":
        if auth.get("requires_sponsorship") is True:
            return "Yes, I will require visa sponsorship.", "draft", cat, "From your profile (work authorization)"
        if auth.get("requires_sponsorship") is False:
            return "No, I do not require sponsorship.", "draft", cat, "From your profile (work authorization)"
        return "", "needs_input", cat, "Sponsorship need not set in your profile"
    if cat == "work_authorization":
        if auth.get("authorized_countries"):
            return ("I am authorized to work in: " + ", ".join(auth["authorized_countries"]) + "."), "draft", cat, "From your profile"
        return "", "needs_input", cat, "Work authorization not set in your profile"
    if cat == "links":
        if profile.links:
            return "\n".join(profile.links), "draft", cat, "From your profile links"
        return "", "needs_input", cat, "No links in your profile"
    if cat in ("salary", "criminal", "demographic", "relocation", "start_date", "years"):
        return "", "needs_input", cat, "Personal information — JobPilot never guesses this. Please answer."
    if re.search(r"tell us about (yourself|your experience)|relevant experience|describe your (background|experience)", q, re.I):
        parts = [profile.summary or profile.headline]
        if profile.experience:
            e = profile.experience[0]
            if e.get("title") and e.get("company"):
                parts.append(f"Most recently I worked as {e['title']} at {e['company']}.")
            if e.get("bullets"):
                parts.append(e["bullets"][0].rstrip(".") + ".")
        text = " ".join(p for p in parts if p).strip()
        if text:
            return text, "draft", cat, "Composed from your verified profile — review before approving"
    return "", "needs_input", cat, "Open question — write or paste your answer."
