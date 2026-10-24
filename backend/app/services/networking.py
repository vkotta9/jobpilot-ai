"""Networking Agent.

JobPilot does not scrape LinkedIn or any people-search site (their terms forbid
it). Instead it generates targeted search queries the user runs themselves; the
user records people they find (with the source URL) and marks them verified.
Outreach drafts are generated from verified profile facts and require approval;
JobPilot never sends messages — the user copies the approved text and marks it
sent, which feeds duplicate-outreach prevention and follow-up reminders.
"""
from __future__ import annotations

from datetime import timedelta
from urllib.parse import quote_plus

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import CandidateProfile, Contact, FollowUpTask, Job, OutreachMessage, utcnow

CONTACT_TYPES = [
    ("recruiter", "Recruiter / talent partner",
     "Recruiters screen candidates for this role and can tell you about timelines and fit.",
     ['"{company}" recruiter', '"{company}" "technical recruiter" OR "talent acquisition"']),
    ("hiring_manager", "Likely hiring manager",
     "The person who leads the team this role sits in usually makes the hiring decision.",
     ['"{company}" "{dept} manager"', '"{company}" "head of {dept}" OR "{dept} lead"']),
    ("team_member", "Peers on the team",
     "People already doing similar work can share what the team values and may refer you.",
     ['"{company}" "{title}"']),
    ("department_leader", "Department leader",
     "Senior leaders set direction for the function; useful context for senior roles.",
     ['"{company}" "director of {dept}" OR "vp {dept}"']),
]


def research_plan(job: Job) -> list[dict]:
    dept = (job.department or "").split(",")[0].strip() or _guess_dept(job.title)
    plan = []
    for ctype, label, why, templates in CONTACT_TYPES:
        queries = []
        for t in templates:
            q = t.format(company=job.company.replace(" (Demo)", ""), dept=dept.lower(), title=_base_title(job.title))
            queries.append({
                "query": q,
                "linkedin_search_url": "https://www.linkedin.com/search/results/people/?keywords=" + quote_plus(q.replace('"', "")),
                "web_search_url": "https://www.google.com/search?q=" + quote_plus(q + " site:linkedin.com/in"),
            })
        plan.append({"contact_type": ctype, "label": label, "why": why, "queries": queries, "verified": False})
    return plan


def _base_title(title: str) -> str:
    import re

    return re.sub(r"\b(senior|sr\.?|junior|jr\.?|staff|principal|lead|ii|iii)\b", "", title, flags=re.I).strip(" -,")


def _guess_dept(title: str) -> str:
    t = title.lower()
    for k, d in [("engineer", "Engineering"), ("developer", "Engineering"), ("data", "Data"), ("design", "Design"),
                 ("product", "Product"), ("market", "Marketing"), ("sales", "Sales"), ("account", "Sales"),
                 ("recruit", "People"), ("finance", "Finance"), ("analyst", "Analytics")]:
        if k in t:
            return d
    return "the team"


def draft_message(profile: CandidateProfile, contact: Contact, job: Job | None, channel: str, kind: str) -> tuple[str, str]:
    first = contact.name.split()[0] if contact.name else "there"
    me = profile.full_name or "[[ADD: your name]]"
    my_role = profile.headline or ((profile.experience or [{}])[0].get("title") if profile.experience else "") or ""
    role_line = f"the {job.title} role" if job else "opportunities on your team"
    company = (job.company if job else contact.company).replace(" (Demo)", "")
    skills = ", ".join((profile.skills or [])[:3])
    subject = ""
    if channel == "linkedin" and kind == "connection":
        body = (f"Hi {first}, I'm {me}{', ' + my_role if my_role else ''}. I'm applying for {role_line} at {company} "
                f"and would value connecting{' given your work as ' + contact.role if contact.role else ''}. Thank you!")
        body = body[:300]  # LinkedIn connection-note limit
    elif kind == "follow_up":
        subject = f"Following up — {job.title if job else 'my application'}"
        body = (f"Hi {first},\n\nI wanted to follow up on my application for {role_line} at {company}. I remain very "
                f"interested and would be glad to share anything else that would help.\n\nThank you,\n{me}")
    else:
        subject = f"{job.title if job else 'Opportunity'} at {company} — {me}"
        body = (f"Hi {first},\n\nI'm {me}{', ' + my_role if my_role else ''}. I recently applied for {role_line} at {company}"
                f"{' and my background in ' + skills + ' lines up closely with it' if skills else ''}.\n\n"
                f"[[ADD: one specific, genuine reason you're reaching out to {first} — e.g. their team's work]]\n\n"
                f"Would you be open to a brief chat, or pointing me to the right person? Thank you for your time.\n\n{me}")
    return subject, body


def ensure_not_duplicate(db: Session, contact: Contact, kind: str) -> None:
    existing = db.query(OutreachMessage).filter(
        OutreachMessage.contact_id == contact.id, OutreachMessage.kind == kind,
        OutreachMessage.status.in_(["draft", "approved", "sent"])).first()
    if existing and kind != "follow_up":
        raise HTTPException(409, f"A {kind} message for {contact.name} already exists (status: {existing.status}). "
                                 "Edit that one instead of creating duplicate outreach.")
    if kind == "follow_up":
        recent = db.query(OutreachMessage).filter(
            OutreachMessage.contact_id == contact.id, OutreachMessage.status == "sent",
            OutreachMessage.sent_at >= utcnow() - timedelta(days=5)).first()
        if recent:
            raise HTTPException(409, f"You messaged {contact.name} less than 5 days ago — give them time before following up.")


def mark_sent(db: Session, msg: OutreachMessage) -> None:
    from .tailoring import PLACEHOLDER_RE

    if msg.status == "sent":
        raise HTTPException(409, "Already marked as sent.")
    if msg.status != "approved":
        raise HTTPException(400, "Approve the message before marking it as sent.")
    if PLACEHOLDER_RE.search(msg.body):
        raise HTTPException(400, "Fill the [[ADD: …]] placeholder first.")
    msg.status, msg.sent_at = "sent", utcnow()
    contact = db.get(Contact, msg.contact_id)
    contact.last_contacted_at = msg.sent_at
    key = f"contact:{contact.id}:followup:{msg.id}"
    if not db.query(FollowUpTask).filter_by(user_id=msg.user_id, dedupe_key=key).first():
        db.add(FollowUpTask(user_id=msg.user_id, contact_id=contact.id, kind="outreach_follow_up", dedupe_key=key,
                            title=f"Check for a reply from {contact.name}", due_at=utcnow() + timedelta(days=7)))
