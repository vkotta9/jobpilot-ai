"""Connections (API keys stored encrypted per user) and one-click automatic job search."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import CandidateProfile, IntegrationSetting, Job, JobSource, User, to_dict, utcnow
from ..security import audit, current_user, owned, rate_limit
from ..services import llm
from ..services.discovery import run_source, search_queries
from ..services.matching import score_job, score_jobs
from ..services.secretbox import mask, seal, unseal
from ..services.sources import ADAPTERS, KEYWORD_KINDS, SourceError
from ..services.sources.keyword import AdzunaAdapter

router = APIRouter(prefix="/api", tags=["integrations"])


class AIIn(BaseModel):
    provider: Literal["openai", "gemini", "custom"] = "gemini"
    api_key: str = Field(default="", max_length=400)
    model: str = Field(default="", max_length=100)
    base_url: str = Field(default="", max_length=300)


class AdzunaIn(BaseModel):
    app_id: str = Field(default="", max_length=100)
    app_key: str = Field(default="", max_length=200)
    country: str = Field(default="us", pattern=r"^[a-z]{2}$")


class MuseIn(BaseModel):
    api_key: str = Field(default="", max_length=200)


def _row(db: Session, user: User, provider: str) -> Optional[IntegrationSetting]:
    return db.query(IntegrationSetting).filter_by(user_id=user.id, provider=provider).one_or_none()


def _save(db: Session, user: User, provider: str, data: dict) -> None:
    row = _row(db, user, provider)
    if row is None:
        db.add(IntegrationSetting(user_id=user.id, provider=provider, data_encrypted=seal(data)))
    else:
        row.data_encrypted, row.updated_at = seal(data), utcnow()
    audit(db, user.id, "integration.save", "integration", None, provider=provider)
    db.commit()


@router.get("/integrations")
def list_integrations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    ai = unseal(_row(db, user, "ai").data_encrypted) if _row(db, user, "ai") else {}
    adz = unseal(_row(db, user, "adzuna").data_encrypted) if _row(db, user, "adzuna") else {}
    muse = unseal(_row(db, user, "muse").data_encrypted) if _row(db, user, "muse") else {}
    env = llm.env_config()
    cfg = llm.config_for(db, user.id)
    return {
        "ai": {"configured": bool(cfg), "source": "app" if ai.get("api_key") else ("server" if env else None),
               "provider": ai.get("provider") or ("openai" if env else None), "model": cfg.model if cfg else None,
               "key_hint": mask(ai.get("api_key", "")), "presets": llm.PRESETS},
        "adzuna": {"configured": bool(adz.get("app_id") and adz.get("app_key")), "app_id_hint": mask(adz.get("app_id", "")),
                   "country": adz.get("country", "us")},
        "muse": {"configured": bool(muse.get("api_key")), "key_hint": mask(muse.get("api_key", ""))},
    }


@router.put("/integrations/ai")
def save_ai(body: AIIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    old = unseal(_row(db, user, "ai").data_encrypted) if _row(db, user, "ai") else {}
    key = body.api_key.strip() or old.get("api_key", "")
    if not key:
        raise HTTPException(400, "Paste your API key.")
    if body.provider == "custom" and not body.base_url.startswith("https://"):
        raise HTTPException(400, "A custom provider needs an https:// base URL (OpenAI-compatible).")
    preset = llm.PRESETS.get(body.provider, {})
    data = {"provider": body.provider, "api_key": key, "model": body.model.strip() or preset.get("model", ""),
            "base_url": body.base_url.strip() or preset.get("base_url", "")}
    _save(db, user, "ai", data)
    return list_integrations(user, db)["ai"]


@router.put("/integrations/adzuna")
def save_adzuna(body: AdzunaIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    old = unseal(_row(db, user, "adzuna").data_encrypted) if _row(db, user, "adzuna") else {}
    data = {"app_id": body.app_id.strip() or old.get("app_id", ""), "app_key": body.app_key.strip() or old.get("app_key", ""),
            "country": body.country}
    if not data["app_id"] or not data["app_key"]:
        raise HTTPException(400, "Both the Adzuna app_id and app_key are needed.")
    _save(db, user, "adzuna", data)
    return list_integrations(user, db)["adzuna"]


@router.put("/integrations/muse")
def save_muse(body: MuseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _save(db, user, "muse", {"api_key": body.api_key.strip()})
    return list_integrations(user, db)["muse"]


@router.delete("/integrations/{provider}")
def delete_integration(provider: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = _row(db, user, provider)
    if row:
        db.delete(row)
        audit(db, user.id, "integration.delete", "integration", None, provider=provider)
        db.commit()
    return {"ok": True}


@router.post("/integrations/{provider}/test", dependencies=[Depends(rate_limit("integration-test", 20, 3600))])
def test_integration(provider: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if provider == "ai":
        cfg = llm.config_for(db, user.id)
        if not cfg:
            raise HTTPException(400, "No AI key saved yet.")
        try:
            return {"ok": True, "message": f"Connected to {llm.test_connection(cfg)}."}
        except llm.LLMError as e:
            raise HTTPException(400, str(e))
    if provider == "adzuna":
        creds = unseal(_row(db, user, "adzuna").data_encrypted) if _row(db, user, "adzuna") else {}
        try:
            n = len(AdzunaAdapter("auto", context={"queries": ["software engineer"], "locations": [], "credentials": creds}).fetch())
            return {"ok": True, "message": f"Adzuna works — test search returned {n} jobs."}
        except SourceError as e:
            raise HTTPException(400, str(e))
    raise HTTPException(400, "Nothing to test for this connection.")


# ---------------------------------------------------------------- automatic job search


class AutoIn(BaseModel):
    kinds: list[Literal["adzuna", "remotive", "muse"]] = Field(default_factory=lambda: ["adzuna", "remotive", "muse"])


@router.get("/discovery/auto")
def auto_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.query(CandidateProfile).filter_by(user_id=user.id).one_or_none()
    prefs = (profile.preferences or {}) if profile else {}
    srcs = {s.kind: to_dict(s) for s in db.query(JobSource).filter(JobSource.user_id == user.id,
                                                                    JobSource.kind.in_(KEYWORD_KINDS)).all()}
    adz = _row(db, user, "adzuna")
    return {
        "queries": search_queries(profile), "titles_from_profile": bool(prefs.get("target_titles")),
        "locations": prefs.get("locations") or [],
        "sources": [{"kind": k, "label": ADAPTERS[k].label, "needs_key": ADAPTERS[k].requires_credentials,
                     "key_ok": (k != "adzuna") or bool(adz), "source": srcs.get(k)} for k in KEYWORD_KINDS],
    }


@router.post("/discovery/auto", dependencies=[Depends(rate_limit("discovery", 30, 3600))])
def auto_run(body: AutoIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.query(CandidateProfile).filter_by(user_id=user.id).one_or_none()
    if not search_queries(profile):
        raise HTTPException(400, "Add the job titles you want (Profile → Job preferences → Target job titles) first.")
    results = []
    changed: list[int] = []
    for kind in KEYWORD_KINDS:
        src = db.query(JobSource).filter_by(user_id=user.id, kind=kind, identifier="auto").one_or_none()
        if kind not in body.kinds:
            if src:
                src.enabled = False
            continue
        if kind == "adzuna" and not _row(db, user, "adzuna"):
            results.append({"kind": kind, "error": "Connect a free Adzuna key in Settings → Connections to search all US job boards.",
                            "new": 0, "updated": 0})
            continue
        if src is None:
            src = JobSource(user_id=user.id, kind=kind, identifier="auto", display_name=ADAPTERS[kind].label)
            db.add(src)
            db.flush()
        src.enabled = True
        r = run_source(db, src)
        changed += r.pop("changed_job_ids", []) or []
        results.append(r)
    db.commit()
    if changed:
        score_jobs(db, user.id, changed)
    return {"results": results, "queries": search_queries(profile)}


class DescriptionIn(BaseModel):
    description_text: str = Field(min_length=50, max_length=60000)


@router.put("/jobs/{jid}/description")
def paste_description(jid: int, body: DescriptionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Replace a short listing snippet with the full description the user copied from the posting."""
    job = owned(db, Job, jid, user)
    job.description_text = body.description_text.strip()
    audit(db, user.id, "job.description_pasted", "job", job.id)
    db.commit()
    m = score_job(db, job)
    db.commit()
    return {"ok": True, "score": m.score if m else None}
