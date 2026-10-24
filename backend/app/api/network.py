"""Networking workspace: research plans, contacts, approval-gated outreach drafts."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Application, CandidateProfile, Contact, Job, OutreachMessage, User, to_dict, utcnow
from ..schemas import ApproveIn, ContactIn, OutreachEdit, OutreachGenerateIn
from ..security import audit, current_user, owned
from ..services import networking

router = APIRouter(prefix="/api", tags=["networking"])


@router.get("/jobs/{jid}/research-plan")
def research_plan(jid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = owned(db, Job, jid, user)
    return {
        "job_id": job.id,
        "note": "JobPilot does not scrape LinkedIn or people-search sites. Run these searches yourself, then add "
                "people you find with their profile URL as the source. Nothing below is a verified person.",
        "plan": networking.research_plan(job),
        "sequence": [
            "Day 0: connect with the recruiter (short note) and, if senior-relevant, the likely hiring manager.",
            "Day 0–2: once connected, send one concise message referencing the role.",
            "Day 7: one polite follow-up if there is no reply. Then stop — never more than two unanswered messages.",
        ],
    }


def _contact_out(c: Contact, db: Session) -> dict:
    d = to_dict(c)
    d["messages"] = [to_dict(m) for m in db.query(OutreachMessage).filter_by(contact_id=c.id).order_by(OutreachMessage.id).all()]
    return d


@router.get("/contacts")
def list_contacts(job_id: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(Contact).filter_by(user_id=user.id)
    if job_id:
        q = q.filter_by(job_id=job_id)
    return [_contact_out(c, db) for c in q.order_by(Contact.id.desc()).all()]


@router.post("/contacts")
def add_contact(body: ContactIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.job_id:
        job = owned(db, Job, body.job_id, user)
        company = body.company or job.company
    else:
        company = body.company
    if body.verified and not body.source_url.startswith(("http://", "https://")):
        raise HTTPException(400, "A verified contact needs the public source URL where you confirmed their role.")
    dup = db.query(Contact).filter_by(user_id=user.id, name=body.name.strip(), company=company).first()
    if dup:
        raise HTTPException(409, f"{body.name} at {company} is already in your contacts.")
    c = Contact(user_id=user.id, **(body.model_dump() | {"company": company, "name": body.name.strip()}))
    db.add(c)
    audit(db, user.id, "contact.add", "contact", None, verified=body.verified)
    db.commit()
    return _contact_out(c, db)


@router.patch("/contacts/{cid}")
def edit_contact(cid: int, body: ContactIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = owned(db, Contact, cid, user)
    if body.verified and not body.source_url.startswith(("http://", "https://")):
        raise HTTPException(400, "A verified contact needs a source URL.")
    for k, v in body.model_dump(exclude={"job_id"}).items():
        setattr(c, k, v)
    db.commit()
    return _contact_out(c, db)


@router.delete("/contacts/{cid}")
def delete_contact(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(owned(db, Contact, cid, user))
    db.commit()
    return {"ok": True}


@router.post("/contacts/{cid}/outreach")
def generate_outreach(cid: int, body: OutreachGenerateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = owned(db, Contact, cid, user)
    networking.ensure_not_duplicate(db, c, body.kind)
    p = db.query(CandidateProfile).filter_by(user_id=user.id).one()
    job = db.get(Job, c.job_id) if c.job_id else None
    subject, text = networking.draft_message(p, c, job, body.channel, body.kind)
    m = OutreachMessage(user_id=user.id, contact_id=c.id, job_id=c.job_id, channel=body.channel, kind=body.kind,
                        subject=subject, body=text)
    db.add(m)
    db.commit()
    return to_dict(m)


@router.put("/outreach/{mid}")
def edit_outreach(mid: int, body: OutreachEdit, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = owned(db, OutreachMessage, mid, user)
    if m.status == "sent":
        raise HTTPException(400, "Sent messages are kept as a record and cannot be edited.")
    if body.body is not None:
        if m.channel == "linkedin" and m.kind == "connection" and len(body.body) > 300:
            raise HTTPException(400, "LinkedIn connection notes are limited to 300 characters.")
        m.body = body.body
    if body.subject is not None:
        m.subject = body.subject
    m.status, m.approved_at = "draft", None
    db.commit()
    return to_dict(m)


@router.post("/outreach/{mid}/approve")
def approve_outreach(mid: int, body: ApproveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from ..services.tailoring import PLACEHOLDER_RE

    m = owned(db, OutreachMessage, mid, user)
    if not body.confirm:
        raise HTTPException(400, "Confirm that you reviewed this message.")
    if PLACEHOLDER_RE.search(m.body):
        raise HTTPException(400, "Fill the [[ADD: …]] placeholder before approving.")
    m.status, m.approved_at = "approved", utcnow()
    audit(db, user.id, "outreach.approve", "outreach_message", m.id)
    db.commit()
    return to_dict(m)


@router.post("/outreach/{mid}/mark-sent")
def mark_sent(mid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = owned(db, OutreachMessage, mid, user)
    networking.mark_sent(db, m)
    if m.job_id:
        app = db.query(Application).filter_by(user_id=user.id, job_id=m.job_id).one_or_none()
        if app:
            app.last_contact_at = m.sent_at
    audit(db, user.id, "outreach.sent_by_user", "outreach_message", m.id)
    db.commit()
    return to_dict(m)


@router.delete("/outreach/{mid}")
def delete_outreach(mid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = owned(db, OutreachMessage, mid, user)
    if m.status == "sent":
        raise HTTPException(400, "Sent messages are kept for duplicate-outreach prevention.")
    db.delete(m)
    db.commit()
    return {"ok": True}
