"""Priority companies: checked every hour inside your alert window (default 10 AM–5 PM Eastern, Mon–Fri),
with an email when a new role related to your profile appears there, with its ATS match.

The free Render server sleeps when idle, so a GitHub Actions schedule calls /api/cron/priority every hour; the
server also checks while it's awake. Each company is checked at most once per ~50 minutes, and the times are
evaluated in your time zone, so daylight-saving changes are handled.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..models import Job, JobSource, MatchAssessment, User, UserSettings, utcnow
from . import notify
from .discovery import pause_between_sources, run_source
from .matching import score_jobs

log = logging.getLogger("jobpilot.priority")

DEFAULTS = {"enabled": True, "start_hour": 10, "end_hour": 17, "days": [0, 1, 2, 3, 4], "timezone": "America/New_York",
            "min_score": 0, "email": True}
MIN_GAP = timedelta(minutes=50)
JSEARCH_HOURS = 3.0  # Google Jobs (JSearch) has a small free monthly quota


def config(st: Optional[UserSettings]) -> dict:
    return {**DEFAULTS, **((st.priority_alerts if st else None) or {})}


def in_window(cfg: dict, now_utc: Optional[datetime] = None) -> bool:
    now_utc = now_utc or datetime.now(timezone.utc)
    try:
        local = now_utc.astimezone(ZoneInfo(cfg.get("timezone") or "America/New_York"))
    except Exception:  # noqa: BLE001 - unknown zone name
        local = now_utc.astimezone(ZoneInfo("America/New_York"))
    return local.weekday() in (cfg.get("days") or []) and int(cfg["start_hour"]) <= local.hour <= int(cfg["end_hour"])


def is_due(st: UserSettings, now_utc: Optional[datetime] = None) -> bool:
    cfg = config(st)
    if not cfg["enabled"] or st.automation_paused or not in_window(cfg, now_utc):
        return False
    last = st.priority_last_run_at
    now = (now_utc or datetime.now(timezone.utc)).replace(tzinfo=None)
    return last is None or now - last >= MIN_GAP


def run_for_user(db: Session, user_id: int, *, send: bool = True, transport=None) -> dict:
    """Check every priority company now; email new related roles. Returns a summary."""
    st = db.get(UserSettings, user_id)
    if st is None:
        st = UserSettings(user_id=user_id)
        db.add(st)
        db.flush()
    cfg = config(st)
    sources = db.query(JobSource).filter(JobSource.user_id == user_id, JobSource.priority.is_(True), JobSource.enabled.is_(True)).all()
    result = {"at": utcnow().isoformat() + "Z", "companies": len(sources), "new": 0, "emailed": 0, "baseline": [], "errors": [], "email_error": ""}
    new_ids: list[int] = []
    for i, src in enumerate(sources):
        if i:
            pause_between_sources()
        first = src.last_run_at is None
        try:
            r = run_source(db, src, transport=transport, max_interval_hours=JSEARCH_HOURS if src.kind == "jsearch" else 0.8)
        except Exception as e:  # noqa: BLE001 - one company mustn't stop the rest
            db.rollback()
            result["errors"].append(f"{src.display_name or src.identifier}: {str(e)[:120]}")
            continue
        if r.get("error"):
            result["errors"].append(f"{src.display_name or src.identifier}: {r['error'][:160]}")
        if r.get("changed_job_ids"):
            score_jobs(db, user_id, r["changed_job_ids"])
        if first:
            # the first check lists everything already open — that's your starting point, not "new" postings
            ids = r.get("new_job_ids") or []
            if ids:
                db.query(Job).filter(Job.id.in_(ids)).update({"alerted_at": utcnow()}, synchronize_session=False)
            result["baseline"].append({"company": src.display_name or src.identifier, "open_roles": len(ids)})
        else:
            new_ids += r.get("new_job_ids") or []
    db.commit()
    jobs = alertable(db, user_id, new_ids, int(cfg.get("min_score") or 0))
    result["new"] = len(jobs)
    if jobs and send and cfg.get("email", True):
        ecfg = notify.email_config(db, user_id)
        if ecfg is None:
            result["email_error"] = "Email isn't set up — add a free Resend key in Settings → Connections to get these by email."
        else:
            try:
                subject, body_html, body_text = compose(jobs)
                notify.send_email(ecfg, subject, body_html, body_text)
                result["emailed"] = len(jobs)
            except notify.EmailError as e:
                result["email_error"] = str(e)
    if jobs and (result["emailed"] or not send or not cfg.get("email", True) or result["email_error"].startswith("Email isn't set up")):
        for j, _ in jobs:
            j.alerted_at = utcnow()  # shown in JobPilot either way; don't repeat
    st.priority_last_run_at = utcnow()
    st.priority_last_result = {**result, "jobs": [{"id": j.id, "title": j.title, "company": j.company, "score": s} for j, s in jobs][:20]}
    db.commit()
    return st.priority_last_result


def alertable(db: Session, user_id: int, ids: list[int], min_score: int) -> list[tuple[Job, Optional[int]]]:
    if not ids:
        return []
    out = []
    for j in db.query(Job).filter(Job.user_id == user_id, Job.id.in_(ids), Job.alerted_at.is_(None),
                                  Job.duplicate_of_id.is_(None), Job.listing_status == "active").all():
        if j.triage in ("skipped", "deleted") or j.application is not None:
            continue
        m = db.query(MatchAssessment).filter_by(job_id=j.id).order_by(MatchAssessment.id.desc()).first()
        if m is not None and m.edu_status == "below":
            continue  # needs a higher degree than yours
        score = m.score if m else None
        if min_score and (score is None or score < min_score):
            continue
        out.append((j, score))
    out.sort(key=lambda x: -(x[1] or 0))
    return out


def compose(jobs: list[tuple[Job, Optional[int]]]) -> tuple[str, str, str]:
    base = notify.PUBLIC_URL["value"]
    companies = sorted({j.company for j, _ in jobs})
    n = len(jobs)
    subject = (f"🎯 New at {companies[0]}: {jobs[0][0].title}" if n == 1 else
               f"🎯 {n} new roles at {', '.join(companies[:3])}{' +' + str(len(companies) - 3) if len(companies) > 3 else ''} match your profile")
    rows, lines = [], []
    for j, s in jobs:
        color = "#15803d" if (s or 0) >= 70 else "#b45309" if (s or 0) >= 50 else "#b91c1c"
        jp = f"{base}/#/jobs/{j.id}" if base else ""
        posted = j.posted_at.strftime("%b %d") if j.posted_at else "just now"
        rows.append(
            f'<tr><td style="padding:12px 0;border-bottom:1px solid #eee">'
            f'<div style="font:600 15px system-ui,Segoe UI,Arial">{html.escape(j.title)}</div>'
            f'<div style="font:13px system-ui,Segoe UI,Arial;color:#555">{html.escape(j.company)} · {html.escape(j.location or "Location not listed")} · posted {posted}</div>'
            f'<div style="margin-top:6px;font:13px system-ui,Segoe UI,Arial">'
            f'<span style="display:inline-block;padding:2px 8px;border-radius:99px;background:{color};color:#fff;font-weight:600">'
            f'ATS {s if s is not None else "–"}</span> '
            + (f'&nbsp;<a href="{html.escape(jp)}" style="color:#5b4fe9;font-weight:600">View &amp; apply in JobPilot →</a>' if jp else "")
            + (f'&nbsp;·&nbsp;<a href="{html.escape(j.url)}" style="color:#555">Official posting</a>' if j.url else "")
            + "</div></td></tr>")
        lines.append(f"- {j.title} — {j.company} ({j.location or 'n/a'}) · ATS {s if s is not None else '-'}\n  {jp or j.url}")
    body_html = (
        '<div style="max-width:620px;margin:0 auto;padding:16px;font:14px system-ui,Segoe UI,Arial;color:#1f2337">'
        f'<h2 style="margin:0 0 4px">{n} new role{"s" if n != 1 else ""} at your priority companies</h2>'
        '<p style="color:#555;margin:0 0 8px">These match your target titles. The ATS score is how well your resume matches each posting.</p>'
        f'<table style="width:100%;border-collapse:collapse">{"".join(rows)}</table>'
        '<p style="color:#888;font-size:12px;margin-top:16px">You get this because these companies are marked ★ priority in JobPilot. '
        "Change the companies, hours or minimum score in Discover → Priority companies.</p></div>")
    body_text = f"{n} new role(s) at your priority companies:\n\n" + "\n".join(lines)
    return subject, body_html, body_text


def tick_all(db_factory) -> list[int]:
    """Run the hourly check for every user who is due right now."""
    from ..scheduler import user_lock

    ran = []
    with db_factory() as db:
        due = [st.user_id for st in db.query(UserSettings).all() if st.priority_alerts and is_due(st)]
        due = [u for u in due if db.query(JobSource).filter(JobSource.user_id == u, JobSource.priority.is_(True)).count()]
    for uid in due:
        lock = user_lock(uid)
        if not lock.acquire(blocking=False):
            continue
        try:
            with db_factory() as db:
                run_for_user(db, uid)
            ran.append(uid)
        except Exception:  # noqa: BLE001
            log.exception("Priority check failed for user %s", uid)
        finally:
            lock.release()
    return ran
