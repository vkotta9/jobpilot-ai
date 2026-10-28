"""Follow-up Agent (next best action, digest) and analytics.

Analytics distinguish verified outcomes (submissions with a confirmation,
status events) from user-reported ones, and never mix simulated listings into
real metrics unless asked.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy.orm import Session

from ..models import Application, Document, FollowUpTask, Job, MatchAssessment, UserSettings, utcnow
from .applications import package_problems


def next_best_action(db: Session, app: Application) -> str:
    s = app.status
    if s in ("shortlisted", "preparing"):
        probs = package_problems(db, app)
        return probs[0] if probs else "Request approval for your application package."
    if s == "awaiting_approval":
        return "Review the package and approve it." if not app.approved_at else \
            "Open the official application page, submit it yourself, then record the submission."
    if s == "applied":
        if app.follow_up_at and app.follow_up_at < utcnow():
            return "Follow-up is overdue — send a short follow-up message."
        return "Start your interview prep plan, and find a recruiter or hiring manager to contact (Networking tab)."
    if s == "assessment":
        return "Complete the assessment — your prep plan lists the topics to review first."
    if s == "interview":
        return "Work through your interview prep plan; send a thank-you within 24 hours afterwards."
    if s == "offer":
        return "Review the offer details and respond by the deadline."
    return ""


def latest_scores(db: Session, user_id: int) -> dict[int, MatchAssessment]:
    out: dict[int, MatchAssessment] = {}
    for m in db.query(MatchAssessment).filter_by(user_id=user_id).order_by(MatchAssessment.id).all():
        out[m.job_id] = m
    return out


def analytics(db: Session, user_id: int, include_simulated: bool = False) -> dict:
    st = db.get(UserSettings, user_id)
    threshold = st.high_match_threshold if st else 75
    jq = db.query(Job).filter(Job.user_id == user_id, Job.duplicate_of_id.is_(None))
    if not include_simulated:
        jq = jq.filter(Job.is_simulated.is_(False))
    jobs = jq.all()
    job_ids = {j.id for j in jobs}
    scores = {k: v for k, v in latest_scores(db, user_id).items() if k in job_ids}
    apps = [a for a in db.query(Application).filter_by(user_id=user_id).all() if a.job_id in job_ids]
    submitted = [a for a in apps if a.submitted_at]
    verified = [a for a in submitted if a.submission_verified]
    responded = [a for a in submitted if a.status in ("assessment", "interview", "offer", "rejected")]
    interviews = [a for a in submitted if a.status in ("interview", "offer")] + \
                 [a for a in submitted if a.status == "rejected" and _had_interview(db, a)]
    offers = [a for a in apps if a.status == "offer"]
    prepared = [a for a in apps if db.query(Document).filter_by(job_id=a.job_id, status="approved").count()]

    # activity by ISO week (last 12 weeks)
    now = utcnow()
    weeks = []
    for i in range(11, -1, -1):
        start = (now - timedelta(days=now.weekday(), weeks=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        weeks.append({
            "week": start.date().isoformat(),
            "discovered": sum(1 for j in jobs if start <= j.discovered_at < end),
            "applied": sum(1 for a in submitted if start <= a.submitted_at < end),
        })

    def perf(keyf):
        groups = defaultdict(lambda: {"applied": 0, "responses": 0, "interviews": 0})
        for a in submitted:
            k = keyf(a)
            groups[k]["applied"] += 1
            groups[k]["responses"] += a in responded
            groups[k]["interviews"] += a in interviews
        return sorted(({"key": k, **v} for k, v in groups.items()), key=lambda r: -r["applied"])[:10]

    status_counts = Counter(a.status for a in apps)
    return {
        "include_simulated": include_simulated,
        "counts": {
            "jobs_discovered": len(jobs),
            "active_listings": sum(1 for j in jobs if j.listing_status == "active"),
            "high_match_jobs": sum(1 for m in scores.values() if m.score >= threshold),
            "applications_prepared": len(prepared),
            "applications_submitted": len(submitted),
            "submissions_verified": len(verified),
            "submissions_user_reported": len(submitted) - len(verified),
            "interviews": len(set(a.id for a in interviews)),
            "offers": len(offers),
        },
        "rates": {
            "response_rate": round(len(responded) / len(submitted), 3) if submitted else None,
            "interview_rate": round(len(set(a.id for a in interviews)) / len(submitted), 3) if submitted else None,
        },
        "status_counts": {s: status_counts.get(s, 0) for s in
                          ["shortlisted", "preparing", "awaiting_approval", "applied", "assessment", "interview", "offer", "rejected", "withdrawn"]},
        "activity": weeks,
        "by_source": perf(lambda a: a.job.source_kind),
        "by_company": perf(lambda a: a.job.company),
        "by_role": perf(lambda a: a.job.title),
        "high_match_threshold": threshold,
        "notes": "Rates use submitted applications as the denominator. 'Verified' = you saved a confirmation "
                 "(email text / number); 'user-reported' = you marked it submitted without one.",
    }


def _had_interview(db: Session, a: Application) -> bool:
    from ..models import ApplicationEvent

    return db.query(ApplicationEvent).filter_by(application_id=a.id, to_status="interview").count() > 0


def attention_items(db: Session, user_id: int) -> list[dict]:
    items = []
    now = utcnow()
    for a in db.query(Application).filter(Application.user_id == user_id,
                                          Application.status.notin_(["rejected", "withdrawn"])).all():
        action = next_best_action(db, a)
        overdue = bool(a.follow_up_at and a.follow_up_at < now and a.status == "applied")
        if a.status in ("shortlisted", "preparing", "awaiting_approval") or overdue:
            items.append({"application_id": a.id, "job_id": a.job_id, "title": a.job.title, "company": a.job.company,
                          "status": a.status, "action": action, "overdue": overdue})
    for t in db.query(FollowUpTask).filter(FollowUpTask.user_id == user_id, FollowUpTask.done.is_(False),
                                           FollowUpTask.due_at < now).all():
        items.append({"task_id": t.id, "title": t.title, "status": "task", "action": "Overdue task", "overdue": True,
                      "application_id": t.application_id})
    return items[:30]


def digest(db: Session, user_id: int, days: int = 7) -> dict:
    since = utcnow() - timedelta(days=days)
    st = db.get(UserSettings, user_id)
    threshold = st.high_match_threshold if st else 75
    scores = latest_scores(db, user_id)
    new_jobs = db.query(Job).filter(Job.user_id == user_id, Job.discovered_at >= since, Job.duplicate_of_id.is_(None)).all()
    high = sorted([j for j in new_jobs if j.id in scores and scores[j.id].score >= threshold],
                  key=lambda j: -scores[j.id].score)
    upcoming = db.query(FollowUpTask).filter(FollowUpTask.user_id == user_id, FollowUpTask.done.is_(False),
                                             FollowUpTask.due_at <= utcnow() + timedelta(days=days)).order_by(FollowUpTask.due_at).all()
    return {
        "period_days": days,
        "new_jobs": len(new_jobs),
        "high_match": [{"job_id": j.id, "title": j.title, "company": j.company, "score": scores[j.id].score,
                        "simulated": j.is_simulated} for j in high[:10]],
        "tasks_due": [{"id": t.id, "title": t.title, "due_at": t.due_at.isoformat() + "Z", "overdue": t.due_at < utcnow()} for t in upcoming],
        "attention": attention_items(db, user_id),
    }
