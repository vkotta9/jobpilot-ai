"""Profile Agent endpoints: verified profile + immutable master resume library."""
from __future__ import annotations

import os
import re
import secrets

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import CandidateProfile, ProfileRevision, Resume, User, to_dict, utcnow
from ..schemas import ProfileIn, ProfilePatch
from ..security import audit, current_user, owned, rate_limit
from ..services import resume_parser
from ..services.matching import score_jobs
from ..services.textutil import sha256

router = APIRouter(prefix="/api", tags=["profile"])

PROFILE_FIELDS = ["full_name", "email", "phone", "location", "headline", "summary", "links", "skills", "experience",
                  "education", "certifications", "projects", "preferences", "work_authorization", "match_weights"]


def get_profile(db: Session, user: User) -> CandidateProfile:
    p = db.query(CandidateProfile).filter_by(user_id=user.id).one_or_none()
    if p is None:
        p = CandidateProfile(user_id=user.id, email=user.email)
        db.add(p)
        db.flush()
    return p


def profile_out(p: CandidateProfile) -> dict:
    from sqlalchemy.orm import object_session

    from ..services.matching import WEIGHT_PRESETS, auto_preset, effective_weights, resolve_preset

    d = to_dict(p)
    db = object_session(p)
    r = db.query(Resume).filter_by(user_id=p.user_id, is_primary=True).one_or_none() if db else None
    text = r.text if r else ""
    d["ats_weights"] = {"preset": resolve_preset(p.match_weights or {}), "auto_choice": auto_preset(text, p),
                        "effective": effective_weights(p.match_weights or {}, text, p), "presets": WEIGHT_PRESETS}
    d["complete"] = bool(p.full_name and p.experience and p.skills)
    return d


@router.get("/profile")
def read_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    db.commit()
    return profile_out(p)


def _apply(db: Session, p: CandidateProfile, data: dict, confirm: bool, user: User) -> CandidateProfile:
    db.add(ProfileRevision(user_id=user.id, snapshot={f: getattr(p, f) for f in PROFILE_FIELDS}))
    for k, v in data.items():
        if k in PROFILE_FIELDS and v is not None:
            setattr(p, k, v)
    p.skills = list(dict.fromkeys(s.strip() for s in (p.skills or []) if s and s.strip()))
    if confirm:
        p.confirmed_at = utcnow()
    p.updated_at = utcnow()
    audit(db, user.id, "profile.update", "candidate_profile", p.id, fields=sorted(k for k, v in data.items() if v is not None))
    db.commit()
    rescore_all(db, user.id)  # keep match scores in sync with the profile
    return p


def rescore_all(db: Session, user_id: int) -> None:
    """Re-score every job; big lists run in the background so saving the profile stays instant."""
    from ..models import Job

    n = db.query(Job).filter(Job.user_id == user_id).count()
    if n <= 300:
        score_jobs(db, user_id)
        return
    import threading

    from ..db import session_scope
    from ..scheduler import user_lock

    def work():
        lock = user_lock(user_id)
        with lock:  # wait for any running search to finish first
            with session_scope() as bg:
                score_jobs(bg, user_id)

    threading.Thread(target=work, daemon=True).start()


@router.put("/profile")
def replace_profile(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    return profile_out(_apply(db, p, body.model_dump(exclude={"confirm"}), body.confirm, user))


@router.patch("/profile")
def patch_profile(body: ProfilePatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = get_profile(db, user)
    return profile_out(_apply(db, p, body.model_dump(exclude={"confirm"}, exclude_none=True), body.confirm, user))


@router.get("/profile/revisions")
def revisions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(ProfileRevision).filter_by(user_id=user.id).order_by(ProfileRevision.id.desc()).limit(50).all()
    return [{"id": r.id, "created_at": r.created_at.isoformat() + "Z"} for r in rows]


@router.post("/profile/revisions/{rev_id}/restore")
def restore(rev_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rev = owned(db, ProfileRevision, rev_id, user)
    p = get_profile(db, user)
    return profile_out(_apply(db, p, dict(rev.snapshot), False, user))


# ---------------------------------------------------------------- resumes


def _resume_out(r: Resume) -> dict:
    return to_dict(r, exclude=("storage_name",))


@router.get("/resumes")
def list_resumes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [_resume_out(r) for r in db.query(Resume).filter_by(user_id=user.id).order_by(Resume.id.desc()).all()]


@router.post("/resumes", dependencies=[Depends(rate_limit("upload", 20, 3600))])
async def upload_resume(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = await file.read(settings.max_upload_bytes + 1)
    try:
        kind = resume_parser.validate_upload(file.filename or "", data, settings.max_upload_bytes)
        text = resume_parser.extract_text(kind, data)
    except resume_parser.UploadError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(400, "Could not read this file. Try re-exporting it as PDF or DOCX.")
    digest = sha256(data.hex())
    existing = db.query(Resume).filter_by(user_id=user.id, sha256=digest).first()
    if existing:
        return {"resume": _resume_out(existing), "duplicate": True}
    folder = settings.upload_dir / str(user.id)
    folder.mkdir(parents=True, exist_ok=True)
    storage_name = f"{secrets.token_hex(16)}.{kind}"  # never trust the client filename for paths
    path = folder / storage_name
    try:  # local copy is a convenience; the DB copy is authoritative
        path.write_bytes(data)
        os.chmod(path, 0o600)
    except OSError:
        pass
    parsed = resume_parser.parse_resume_text(text)
    first = db.query(Resume).filter_by(user_id=user.id).count() == 0
    r = Resume(user_id=user.id, original_filename=os.path.basename(file.filename or f"resume.{kind}")[:255],
               storage_name=storage_name, mime_type=kind, size_bytes=len(data), sha256=digest, file_data=data, text=text,
               parsed=parsed, is_primary=first)
    db.add(r)
    audit(db, user.id, "resume.upload", "resume", None, filename=r.original_filename)
    db.commit()
    return {"resume": _resume_out(r), "duplicate": False}


@router.post("/resumes/{rid}/primary")
def make_primary(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = owned(db, Resume, rid, user)
    db.query(Resume).filter_by(user_id=user.id).update({"is_primary": False})
    r.is_primary = True
    db.commit()
    return _resume_out(r)


@router.post("/resumes/{rid}/apply-to-profile")
def apply_to_profile(rid: int, overwrite: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Copy parsed resume data into the profile. By default only EMPTY fields are
    filled, so existing (confirmed) information is never lost."""
    r = owned(db, Resume, rid, user)
    p = get_profile(db, user)
    parsed = r.parsed or {}
    updates = {}
    for f in ["full_name", "email", "phone", "headline", "summary", "links", "skills", "experience", "education",
              "certifications", "projects"]:
        val = parsed.get(f)
        if not val:
            continue
        cur = getattr(p, f)
        if overwrite or not cur:
            updates[f] = val
        elif f == "skills":
            merged = list(dict.fromkeys(list(cur) + list(val)))
            if merged != list(cur):
                updates[f] = merged
    _apply(db, p, updates, False, user)
    return {"profile": profile_out(p), "updated_fields": sorted(updates)}


@router.get("/resumes/{rid}/file")
def download_resume(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = owned(db, Resume, rid, user)
    media = "application/pdf" if r.mime_type == "pdf" else \
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if r.file_data:
        safe = re.sub(r'[^A-Za-z0-9._ -]', "_", r.original_filename)
        return Response(r.file_data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{safe}"'})
    path = settings.upload_dir / str(user.id) / r.storage_name
    if not path.exists():
        raise HTTPException(404, "File missing from storage")
    return FileResponse(path, media_type=media, filename=r.original_filename)


@router.delete("/resumes/{rid}")
def delete_resume(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = owned(db, Resume, rid, user)
    path = settings.upload_dir / str(user.id) / r.storage_name
    if path.exists():
        path.unlink()
    db.delete(r)
    audit(db, user.id, "resume.delete", "resume", rid)
    db.commit()
    return {"ok": True}
