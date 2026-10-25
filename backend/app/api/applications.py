"""Materials (resume / cover letter), application package, approval and tracker."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    Application,
    ApplicationEvent,
    CandidateProfile,
    Contact,
    Document,
    FollowUpTask,
    Interview,
    Job,
    Resume,
    ScreeningAnswer,
    User,
    to_dict,
    utcnow,
)
from ..schemas import (
    AnswerEdit,
    ApplicationPatch,
    ApproveIn,
    DocumentEdit,
    InterviewIn,
    QuestionsIn,
    StatusChange,
    SubmissionRecord,
)
from ..security import audit, current_user, owned, rate_limit
from ..services import applications as appsvc
from ..services import export, inplace_pdf, llm, tailor_inplace
from ..services.inplace_pdf import FitError
from ..services.insights import latest_scores, next_best_action
from ..services.matching import assess
from ..services.tailoring import cover_letter, tailor_resume, unresolved_placeholders, validate_resume_edit
from .serialize import app_out, doc_out

router = APIRouter(prefix="/api", tags=["applications"])


def _profile(db: Session, user: User) -> CandidateProfile:
    p = db.query(CandidateProfile).filter_by(user_id=user.id).one_or_none()
    has_file = db.query(Resume).filter_by(user_id=user.id, is_primary=True).count() > 0
    if not p or not (p.experience or p.skills or has_file):
        raise HTTPException(400, "Complete your profile (experience and skills) before generating materials.")
    return p


def _next_version(db: Session, job_id: int, kind: str) -> int:
    last = appsvc.latest_doc(db, job_id, kind)
    return (last.version + 1) if last else 1


def _invalidate_for_job(db: Session, job_id: int, user_id: int, reason: str) -> None:
    app = db.query(Application).filter_by(user_id=user_id, job_id=job_id).one_or_none()
    if app:
        appsvc.invalidate_approval(db, app, reason)


# ---------------------------------------------------------------- documents


@router.post("/jobs/{jid}/resume/tailor", dependencies=[Depends(rate_limit("generate", 60, 3600))])
def generate_resume(jid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = owned(db, Job, jid, user)
    p = _profile(db, user)
    resume = db.query(Resume).filter_by(user_id=user.id, is_primary=True).one_or_none()
    if resume is not None and resume.mime_type in ("pdf", "docx") and tailor_inplace.resume_bytes(resume) is not None:
        # keep the user's own file and format; only re-word lines and add skills
        try:
            content, flags, generator = tailor_inplace.build_plan(db, user.id, job, resume)
            out, _ = tailor_inplace.render(content, resume)
            content["ats_after"] = tailor_inplace.ats_after(content, out, job)
        except (ValueError, FitError) as e:
            raise HTTPException(400, str(e))
    else:
        content, flags, generator = tailor_resume(p, job, resume.text if resume else "", cfg=llm.config_for(db, user.id))
    d = Document(user_id=user.id, job_id=job.id, kind="resume", version=_next_version(db, job.id, "resume"),
                 content=content, flags=flags, generator=generator)
    db.add(d)
    app = appsvc.get_or_create(db, job)
    if app.status == "shortlisted":
        app.status = "preparing"
        appsvc.event(db, app, "status", "shortlisted", "preparing", "Tailored resume generated")
    appsvc.invalidate_approval(db, app, "New resume version generated")
    audit(db, user.id, "document.generate", "document", None, kind="resume", job_id=job.id)
    db.commit()
    return doc_out(d)


@router.post("/jobs/{jid}/cover-letter", dependencies=[Depends(rate_limit("generate", 60, 3600))])
def generate_letter(jid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = owned(db, Job, jid, user)
    p = _profile(db, user)
    resume = db.query(Resume).filter_by(user_id=user.id, is_primary=True).one_or_none()
    a = assess(job, p, resume.text if resume else "")
    content, flags, generator = cover_letter(p, job, a, cfg=llm.config_for(db, user.id))
    d = Document(user_id=user.id, job_id=job.id, kind="cover_letter", version=_next_version(db, job.id, "cover_letter"),
                 content=content, flags=flags, generator=generator)
    db.add(d)
    app = appsvc.get_or_create(db, job)
    if app.status == "shortlisted":
        app.status = "preparing"
    appsvc.invalidate_approval(db, app, "New cover letter generated")
    db.commit()
    return doc_out(d)


@router.get("/documents/{did}")
def get_document(did: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = owned(db, Document, did, user)
    out = doc_out(d)
    out["placeholders"] = unresolved_placeholders(d.content)
    if d.content.get("format") == "inplace":
        r = db.get(Resume, d.content["resume_id"])
        raw = tailor_inplace.resume_bytes(r) if r else None
        out["pages"] = inplace_pdf.page_count(raw) if raw and d.content["file_kind"] == "pdf" else 1
        out["resume_available"] = r is not None
        return out
    if d.kind == "resume":
        p = db.query(CandidateProfile).filter_by(user_id=user.id).one()
        out["original"] = {"summary": p.summary, "skills": p.skills, "experience": p.experience}
    return out


@router.put("/documents/{did}")
def edit_document(did: int, body: DocumentEdit, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = owned(db, Document, did, user)
    if d.content.get("format") == "inplace":
        d.content = _merge_inplace_edit(d.content, body.content)
        r = db.get(Resume, d.content["resume_id"])
        job = db.get(Job, d.job_id)
        try:
            out, warnings = _render_inplace(d, r)
        except FitError as e:
            raise HTTPException(400, _fit_message(d.content, str(e)))
        content = dict(d.content)
        content["ats_after"] = tailor_inplace.ats_after(content, out, job)
        content["warnings"] = warnings
        d.content = content
        d.status, d.approved_at = "draft", None
        _invalidate_for_job(db, d.job_id, user.id, "resume edited")
        audit(db, user.id, "document.edit", "document", d.id)
        db.commit()
        return doc_out(d)
    if d.kind == "resume":
        problems = validate_resume_edit(d.content, body.content)
        if problems:
            raise HTTPException(400, " ".join(problems))
        # keep server-owned keys
        body.content["keywords"] = d.content.get("keywords")
        body.content["target"] = d.content.get("target")
        body.content["header"] = d.content.get("header")
    else:
        if not isinstance(body.content.get("body"), str):
            raise HTTPException(400, "Cover letter content must include 'body'.")
        body.content = {"body": body.content["body"][:20000], "target": d.content.get("target")}
    d.content = body.content
    d.status, d.approved_at = "draft", None
    _invalidate_for_job(db, d.job_id, user.id, f"{d.kind} edited")
    audit(db, user.id, "document.edit", "document", d.id)
    db.commit()
    return doc_out(d)


@router.post("/documents/{did}/approve")
def approve_document(did: int, body: ApproveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = owned(db, Document, did, user)
    if not body.confirm:
        raise HTTPException(400, "Confirm that you reviewed this document.")
    ph = unresolved_placeholders(d.content)
    if ph:
        raise HTTPException(400, f"Fill or remove {len(ph)} [[ADD: …]] placeholder(s) before approving.")
    if d.content.get("format") == "inplace":
        try:
            _render_inplace(d, db.get(Resume, d.content["resume_id"]))
        except FitError as e:
            raise HTTPException(400, _fit_message(d.content, str(e)))
    d.status, d.approved_at = "approved", utcnow()
    audit(db, user.id, "document.approve", "document", d.id)
    db.commit()
    return doc_out(d)


@router.delete("/documents/{did}")
def delete_document(did: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = owned(db, Document, did, user)
    app = db.query(Application).filter_by(user_id=user.id, job_id=d.job_id).one_or_none()
    if app and app.submitted_at and did in (app.resume_doc_id, app.cover_letter_doc_id):
        raise HTTPException(400, "This document was part of a submitted application and is kept for your records.")
    _invalidate_for_job(db, d.job_id, user.id, f"{d.kind} deleted")
    db.delete(d)
    db.commit()
    return {"ok": True}


@router.get("/documents/{did}/download")
def download_document(did: int, format: str = "pdf", user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = owned(db, Document, did, user)
    if format not in ("pdf", "docx"):
        raise HTTPException(400, "format must be pdf or docx")
    if d.content.get("format") == "inplace":
        kind = d.content["file_kind"]
        if format != kind:
            raise HTTPException(400, f"This resume keeps your original {kind.upper()} format — download it as {kind.upper()}.")
        try:
            data, _ = _render_inplace(d, db.get(Resume, d.content["resume_id"]))
        except FitError as e:
            raise HTTPException(400, _fit_message(d.content, str(e)))
        stem = re.sub(r"\.(pdf|docx)$", "", d.content.get("resume_filename") or "resume", flags=re.I)
        target = d.content.get("target", {})
        base = re.sub(r"[^A-Za-z0-9]+", "_", f"{stem}_{target.get('company', '')}").strip("_")
        if d.status != "approved":
            base += "_DRAFT"
        media = "application/pdf" if kind == "pdf" else \
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{base}.{kind}"'})
    fn = {("resume", "pdf"): export.resume_pdf, ("resume", "docx"): export.resume_docx,
          ("cover_letter", "pdf"): export.letter_pdf, ("cover_letter", "docx"): export.letter_docx}[(d.kind, format)]
    data = fn(d.content)
    target = d.content.get("target", {})
    base = re.sub(r"[^A-Za-z0-9]+", "_", f"{d.kind}_{target.get('company', '')}_{target.get('title', '')}_v{d.version}").strip("_")
    if d.status != "approved":
        base += "_DRAFT"
    media = "application/pdf" if format == "pdf" else \
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{base}.{format}"'})


@router.get("/documents/{did}/preview.png")
def preview_document(did: int, page: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = owned(db, Document, did, user)
    if d.content.get("format") != "inplace":
        raise HTTPException(400, "Preview is available for format-preserving resumes.")
    r = db.get(Resume, d.content["resume_id"])
    try:
        data, _ = _render_inplace(d, r)
    except FitError as e:
        raise HTTPException(400, _fit_message(d.content, str(e)))
    if d.content["file_kind"] == "pdf":
        png = inplace_pdf.page_png(data, page)
    else:
        raise HTTPException(400, "Live preview is available for PDF resumes; download the DOCX to view it.")
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/resumes/{rid}/preview.png")
def preview_resume(rid: int, page: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = owned(db, Resume, rid, user)
    data = tailor_inplace.resume_bytes(r)
    if not data or r.mime_type != "pdf":
        raise HTTPException(400, "Preview is available for PDF resumes.")
    return Response(inplace_pdf.page_png(data, page), media_type="image/png")


def _render_inplace(d: Document, r: Optional[Resume]):
    if r is None:
        raise HTTPException(400, "The original resume for this document was deleted. Upload it again and re-tailor.")
    try:
        return tailor_inplace.render(d.content, r)
    except ValueError as e:
        if isinstance(e, FitError):
            raise
        raise HTTPException(400, str(e))


def _fit_message(content: dict, msg: str) -> str:
    uid = msg.split(":", 1)[0]
    unit = next((u for u in content.get("units", []) if u["id"] == uid), None)
    where = f"“{tailor_inplace.plain(unit['original'])[:60]}…”" if unit else "one line"
    return f"The new text for {where} doesn't fit in the original space ({msg.split(':', 1)[-1].strip()}). Shorten it a little."


def _merge_inplace_edit(old: dict, new: dict) -> dict:
    """Only per-unit final text/accepted flags and skill selections can change; facts stay server-owned."""
    out = dict(old)
    incoming_units = {u.get("id"): u for u in new.get("units", []) if isinstance(u, dict)}
    units = []
    for u in old["units"]:
        u = dict(u)
        inc = incoming_units.get(u["id"])
        if inc is not None and u["kind"] in ("bullet", "paragraph"):
            final = str(inc.get("final", u["final"]))[:3000]
            u["final"] = final if tailor_inplace.plain(final) else u["original"]
            u["accepted"] = bool(inc.get("accepted", u["accepted"]))
            if u["accepted"] and tailor_inplace.plain(u["final"]) != tailor_inplace.plain(u.get("proposed") or ""):
                if tailor_inplace.plain(u["final"]) != tailor_inplace.plain(u["original"]):
                    u["status"] = "edited"
        units.append(u)
    out["units"] = units
    sel = {s.get("term"): bool(s.get("selected")) for s in new.get("skills", []) if isinstance(s, dict)}
    out["skills"] = [dict(s, selected=sel.get(s["term"], s["selected"])) for s in old.get("skills", [])]
    rem = {(r.get("unit_id"), r.get("display")): bool(r.get("remove")) for r in new.get("skill_removals", []) if isinstance(r, dict)}
    out["skill_removals"] = [dict(r, remove=rem.get((r["unit_id"], r["display"]), r["remove"])) for r in old.get("skill_removals", []) or []]
    return out


# ---------------------------------------------------------------- applications


@router.get("/applications")
def list_applications(status: str = "", q: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    qry = db.query(Application).filter_by(user_id=user.id)
    if status:
        qry = qry.filter(Application.status.in_(status.split(",")))
    scores = latest_scores(db, user.id)
    apps = qry.order_by(Application.updated_at.desc()).all()
    if q:
        ql = q.lower()
        apps = [a for a in apps if ql in a.job.title.lower() or ql in a.job.company.lower()]
    out = []
    for a in apps:
        d = app_out(a, scores.get(a.job_id))
        d["next_best_action"] = next_best_action(db, a)
        d["contacts"] = db.query(Contact).filter_by(user_id=user.id, job_id=a.job_id).count()
        out.append(d)
    return out


@router.get("/applications/export.csv")
def export_csv(user: User = Depends(current_user), db: Session = Depends(get_db)):
    scores = latest_scores(db, user.id)
    rows = []
    for a in db.query(Application).filter_by(user_id=user.id).order_by(Application.id).all():
        j = a.job
        contacts = db.query(Contact).filter_by(user_id=user.id, job_id=j.id).all()
        interviews = db.query(Interview).filter_by(application_id=a.id).all()
        rows.append({
            "company": j.company, "title": j.title, "location": j.location, "remote_type": j.remote_type,
            "salary": f"{j.salary_min or ''}-{j.salary_max or ''} {j.salary_currency}".strip(" -"),
            "source": j.source_kind, "simulated": j.is_simulated, "job_url": j.url, "listing_status": j.listing_status,
            "match_score": scores[j.id].score if j.id in scores else "",
            "status": a.status, "discovered_at": j.discovered_at.isoformat(), "last_checked_at": j.last_checked_at.isoformat(),
            "submitted_at": a.submitted_at.isoformat() if a.submitted_at else "",
            "submission_verified": a.submission_verified, "confirmation": a.confirmation_detail,
            "resume_version": (db.get(Document, a.resume_doc_id).version if a.resume_doc_id and db.get(Document, a.resume_doc_id) else ""),
            "cover_letter_version": (db.get(Document, a.cover_letter_doc_id).version if a.cover_letter_doc_id and db.get(Document, a.cover_letter_doc_id) else ""),
            "follow_up_at": a.follow_up_at.isoformat() if a.follow_up_at else "",
            "last_contact_at": a.last_contact_at.isoformat() if a.last_contact_at else "",
            "contacts": "; ".join(f"{c.name} ({c.role})" for c in contacts),
            "interviews": "; ".join(f"{i.stage} {i.scheduled_at.date() if i.scheduled_at else ''}" for i in interviews),
            "next_action": a.next_action or next_best_action(db, a), "notes": a.notes, "outcome": a.outcome_detail,
        })
    cols = list(rows[0].keys()) if rows else ["company", "title", "status"]
    return Response(export.to_csv(rows, cols), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="jobpilot_tracker.csv"'})


@router.get("/applications/{aid}")
def application_detail(aid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = owned(db, Application, aid, user)
    scores = latest_scores(db, user.id)
    out = app_out(a, scores.get(a.job_id))
    resume = appsvc.latest_doc(db, a.job_id, "resume")
    letter = appsvc.latest_doc(db, a.job_id, "cover_letter")
    out["resume"] = doc_out(resume) if resume else None
    out["resume_used"] = appsvc.resume_choice(db, a)
    out["cover_letter"] = doc_out(letter) if letter else None
    out["answers"] = [to_dict(x) for x in db.query(ScreeningAnswer).filter_by(application_id=a.id).order_by(ScreeningAnswer.id).all()]
    out["events"] = [to_dict(e) for e in db.query(ApplicationEvent).filter_by(application_id=a.id).order_by(ApplicationEvent.id).all()]
    out["interviews"] = [to_dict(i) for i in db.query(Interview).filter_by(application_id=a.id).order_by(Interview.id).all()]
    out["tasks"] = [to_dict(t) for t in db.query(FollowUpTask).filter_by(application_id=a.id).order_by(FollowUpTask.due_at).all()]
    out["problems"] = appsvc.package_problems(db, a)
    out["approval_current"] = appsvc.approval_is_current(db, a)
    out["next_best_action"] = next_best_action(db, a)
    out["allowed_transitions"] = sorted(appsvc.MANUAL_TRANSITIONS.get(a.status, set()))
    return out


def _parse_dt(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "")[:19]) if "T" in s else datetime.fromisoformat(s[:10])
    except ValueError:
        raise HTTPException(400, f"Invalid date: {s}")


@router.patch("/applications/{aid}")
def patch_application(aid: int, body: ApplicationPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = owned(db, Application, aid, user)
    if body.notes is not None:
        a.notes = body.notes[:20000]
    if body.next_action is not None:
        a.next_action = body.next_action[:300]
    if body.outcome_detail is not None:
        a.outcome_detail = body.outcome_detail[:5000]
    if body.follow_up_at is not None:
        a.follow_up_at = _parse_dt(body.follow_up_at)
        if a.follow_up_at:
            key = f"app:{a.id}:manual_follow_up"
            t = db.query(FollowUpTask).filter_by(user_id=user.id, dedupe_key=key).first()
            if t:
                t.due_at, t.done = a.follow_up_at, False
            else:
                db.add(FollowUpTask(user_id=user.id, application_id=a.id, kind="application_follow_up", dedupe_key=key,
                                    title=f"Follow up — {a.job.title} @ {a.job.company}", due_at=a.follow_up_at))
    if body.last_contact_at is not None:
        a.last_contact_at = _parse_dt(body.last_contact_at)
    a.updated_at = utcnow()
    db.commit()
    return app_out(a)


@router.post("/applications/{aid}/status")
def set_status(aid: int, body: StatusChange, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = owned(db, Application, aid, user)
    appsvc.change_status(db, a, body.status, body.detail)
    a.updated_at = utcnow()
    db.commit()
    return app_out(a)


@router.post("/applications/{aid}/request-approval")
def request_approval(aid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = owned(db, Application, aid, user)
    res = appsvc.request_approval(db, a)
    db.commit()
    return res


@router.post("/applications/{aid}/approve")
def approve(aid: int, body: ApproveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = owned(db, Application, aid, user)
    res = appsvc.approve(db, a, body.confirm)
    db.commit()
    return res


@router.post("/applications/{aid}/submission")
def record_submission(aid: int, body: SubmissionRecord, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = owned(db, Application, aid, user)
    res = appsvc.record_submission(db, a, body.confirm, body.method, body.confirmation_detail)
    db.commit()
    return res


@router.post("/applications/{aid}/questions")
def add_questions(aid: int, body: QuestionsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = owned(db, Application, aid, user)
    p = db.query(CandidateProfile).filter_by(user_id=user.id).one()
    created = []
    for q in body.questions:
        q = q.strip()[:2000]
        if not q:
            continue
        if db.query(ScreeningAnswer).filter_by(application_id=a.id, question_key=appsvc.question_key(q)).first():
            continue
        ans, status, cat, src = appsvc.draft_answer(db, p, q)
        sa = ScreeningAnswer(user_id=user.id, application_id=a.id, question=q, question_key=appsvc.question_key(q),
                             category=cat, answer=ans, status=status, source=src)
        db.add(sa)
        created.append(sa)
    appsvc.invalidate_approval(db, a, "Screening questions added")
    db.commit()
    return [to_dict(x) for x in created]


@router.put("/answers/{ans_id}")
def edit_answer(ans_id: int, body: AnswerEdit, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sa = owned(db, ScreeningAnswer, ans_id, user)
    if body.approve and not body.answer.strip():
        raise HTTPException(400, "An empty answer cannot be approved.")
    sa.answer = body.answer
    sa.status = "approved" if body.approve else ("draft" if body.answer.strip() else "needs_input")
    sa.reusable = body.reusable
    sa.source = "Your answer"
    if sa.application_id:
        a = db.get(Application, sa.application_id)
        appsvc.invalidate_approval(db, a, "Screening answer changed")
    db.commit()
    return to_dict(sa)


@router.delete("/answers/{ans_id}")
def delete_answer(ans_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sa = owned(db, ScreeningAnswer, ans_id, user)
    if sa.application_id:
        appsvc.invalidate_approval(db, db.get(Application, sa.application_id), "Screening answer removed")
    db.delete(sa)
    db.commit()
    return {"ok": True}


@router.get("/answers/library")
def answer_library(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(ScreeningAnswer).filter_by(user_id=user.id, reusable=True, status="approved").all()
    return [to_dict(r) for r in rows]


@router.post("/applications/{aid}/interviews")
def add_interview(aid: int, body: InterviewIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = owned(db, Application, aid, user)
    iv = Interview(user_id=user.id, application_id=a.id, stage=body.stage, scheduled_at=_parse_dt(body.scheduled_at),
                   notes=body.notes, outcome=body.outcome)
    db.add(iv)
    if a.status in ("applied", "assessment"):
        appsvc.change_status(db, a, "interview", f"Interview scheduled: {body.stage}")
    if iv.scheduled_at:
        db.add(FollowUpTask(user_id=user.id, application_id=a.id, kind="interview", title=f"{body.stage} — {a.job.company}",
                            due_at=iv.scheduled_at, dedupe_key=f"interview:{a.id}:{body.stage}:{iv.scheduled_at}"))
    db.commit()
    return to_dict(iv)
