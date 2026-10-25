"""JobPilot browser extension: connect, autofill payload for an approved application, submission record, download.

The extension fills the company's real application form (on Greenhouse, Lever, Ashby, Workday, …) with the
user's profile, resume and approved answers. The user reviews it and presses the site's Submit button; the
extension then sees the site's confirmation page and records the submission here (with that text as evidence).
JobPilot itself never submits anything and never touches CAPTCHAs or bot checks.
"""
from __future__ import annotations

import base64
import io
import json
import re
import secrets
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Application, AuthSession, CandidateProfile, Document, Resume, ScreeningAnswer, User, utcnow
from ..security import _hash_token, audit, current_user, owned, rate_limit
from ..services import applications as appsvc
from ..services import ats, export, tailor_inplace

router = APIRouter(prefix="/api", tags=["extension"])

EXT_DIR = Path(__file__).resolve().parents[3] / "extension"
EXT_TOKEN_DAYS = 180


@router.post("/extension/connect", dependencies=[Depends(rate_limit("ext-connect", 20, 3600))])
def connect(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """A separate long-lived token for the extension (the browser session cookie stays httpOnly)."""
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=_hash_token(token), user_id=user.id, expires_at=utcnow() + timedelta(days=EXT_TOKEN_DAYS)))
    audit(db, user.id, "extension.connect", "user", user.id)
    db.commit()
    return {"token": token, "email": user.email, "expires_in_days": EXT_TOKEN_DAYS}


@router.get("/extension/ping")
def ping(user: User = Depends(current_user)):
    return {"ok": True, "email": user.email}


def _split_name(full: str) -> tuple[str, str]:
    parts = (full or "").split()
    return (parts[0], " ".join(parts[1:])) if len(parts) > 1 else ((parts[0], "") if parts else ("", ""))


def _link(links: list[str], rx: str) -> str:
    return next((l for l in links or [] if re.search(rx, l, re.I)), "")


def _year(s: str) -> str:
    m = re.search(r"(19|20)\d{2}", s or "")
    return m.group(0) if m else ""


def _resume_file(db: Session, app: Application, first: str, last: str) -> Optional[dict]:
    choice = appsvc.resume_choice(db, app)
    stem = re.sub(r"[^A-Za-z0-9]+", "_", f"{first} {last} Resume").strip("_") or "Resume"
    if choice["type"] == "tailored":
        d = db.get(Document, choice["doc_id"])
        if d.content.get("format") == "inplace":
            r = db.get(Resume, d.content["resume_id"])
            data, _ = tailor_inplace.render(d.content, r)
            kind = d.content["file_kind"]
        else:
            data, kind = export.resume_pdf(d.content), "pdf"
    elif choice["type"] == "master":
        r = db.get(Resume, choice["resume_id"])
        data = tailor_inplace.resume_bytes(r)
        if data is None:
            return None
        kind = r.mime_type if r.mime_type in ("pdf", "docx") else "pdf"
    else:
        return None
    mime = "application/pdf" if kind == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return {"filename": f"{stem}.{kind}", "mime": mime, "base64": base64.b64encode(data).decode()}


@router.get("/applications/{aid}/autofill")
def autofill(aid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = owned(db, Application, aid, user)
    if app.submitted_at:
        raise HTTPException(409, "This application was already submitted.")
    if not appsvc.approval_is_current(db, app):
        raise HTTPException(400, "Approve this application package in JobPilot first.")
    p = db.query(CandidateProfile).filter_by(user_id=user.id).one_or_none()
    if p is None:
        raise HTTPException(400, "Fill in your profile first.")
    first, last = _split_name(p.full_name)
    loc = [x.strip() for x in (p.location or "").split(",") if x.strip()]
    auth = p.work_authorization or {}
    countries = auth.get("authorized_countries") or []
    exp = (p.experience or [{}])[0] if p.experience else {}
    edu = (p.education or [{}])[0] if p.education else {}
    master = appsvc.master_resume(db, user.id)
    years = ats.resume_years(master.text or "") if master is not None else None
    answers = db.query(ScreeningAnswer).filter(ScreeningAnswer.user_id == user.id, ScreeningAnswer.status == "approved",
                                               (ScreeningAnswer.application_id == app.id) | ScreeningAnswer.reusable.is_(True)).all()
    letter_doc = appsvc.latest_doc(db, app.job_id, "cover_letter")
    letter = None
    if letter_doc is not None and letter_doc.status == "approved":
        stem = re.sub(r"[^A-Za-z0-9]+", "_", f"{first} {last} Cover Letter").strip("_")
        letter = {"text": letter_doc.content.get("body", ""), "filename": f"{stem}.pdf", "mime": "application/pdf",
                  "base64": base64.b64encode(export.letter_pdf(letter_doc.content)).decode()}
    job = app.job
    audit(db, user.id, "extension.autofill", "application", app.id)
    db.commit()
    return {
        "application_id": app.id,
        "job": {"title": job.title, "company": job.company, "url": job.apply_url or job.url},
        "profile": {
            "first_name": first, "last_name": last, "full_name": p.full_name, "email": p.email or user.email, "phone": p.phone,
            "location": p.location, "city": loc[0] if loc else "", "state": loc[1] if len(loc) > 1 else "",
            "country": (loc[2] if len(loc) > 2 else (countries[0] if countries else "")),
            "linkedin": _link(p.links, r"linkedin\.com"), "github": _link(p.links, r"github\.com"),
            "website": next((l for l in p.links or [] if not re.search(r"linkedin\.com|github\.com", l, re.I)), ""),
            "current_company": exp.get("company", ""), "current_title": exp.get("title", ""),
            "school": edu.get("institution", ""), "degree": edu.get("degree", ""), "field": edu.get("field", ""),
            "grad_year": _year(edu.get("end", "")), "years_experience": years,
        },
        "work_auth": {"authorized_countries": countries, "requires_sponsorship": auth.get("requires_sponsorship")},
        "answers": [{"question": a.question, "answer": a.answer, "category": a.category} for a in answers],
        "resume": _resume_file(db, app, first, last),
        "cover_letter": letter,
    }


class ExtSubmitted(BaseModel):
    confirmation_detail: str = Field(default="", max_length=4000)
    page_url: str = Field(default="", max_length=2000)


@router.post("/applications/{aid}/extension-submitted")
def extension_submitted(aid: int, body: ExtSubmitted, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The user pressed Submit on the company's site and the extension saw its confirmation page."""
    app = owned(db, Application, aid, user)
    detail = body.confirmation_detail.strip()
    if body.page_url:
        detail = (detail + f"\n\nConfirmation page: {body.page_url}").strip()
    r = appsvc.record_submission(db, app, True, "extension_autofill", detail)
    db.commit()
    return r


@router.get("/extension/jobpilot-extension.zip", include_in_schema=False)
def download_extension(request: Request):
    """The extension, set up for this JobPilot site (its address goes into the manifest)."""
    if not EXT_DIR.exists():
        raise HTTPException(404, "Extension files are missing on this server.")
    base = str(request.base_url).rstrip("/")
    proto = request.headers.get("x-forwarded-proto")
    if proto and base.startswith("http://") and proto == "https":
        base = "https://" + base[len("http://"):]
    u = urlparse(base)
    origin_pattern = f"{u.scheme}://{u.hostname}/*"  # match patterns ignore ports
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(EXT_DIR.rglob("*")):
            if f.is_dir():
                continue
            rel = f.relative_to(EXT_DIR).as_posix()
            data = f.read_bytes()
            if rel == "manifest.json":
                m = json.loads(data)
                for cs in m.get("content_scripts", []):
                    cs["matches"] = [origin_pattern]
                hp = m.setdefault("host_permissions", [])
                if origin_pattern not in hp:
                    hp.append(origin_pattern)
                data = json.dumps(m, indent=2).encode()
            elif rel == "config.js":
                data = f"self.JOBPILOT_ORIGIN = {json.dumps(f'{u.scheme}://{u.netloc}')};\n".encode()
            z.writestr(f"jobpilot-extension/{rel}", data)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="jobpilot-extension.zip"'})
