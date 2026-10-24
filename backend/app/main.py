"""JobPilot AI — FastAPI application entry point.

Run:  uvicorn app.main:app --reload   (from the backend/ directory)
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import applications, auth, integrations, jobs, misc, network, profile
from .config import PROJECT_DIR, settings
from .migrations import run_migrations

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("jobpilot")
FRONTEND_DIR = PROJECT_DIR / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    try:
        _rescore_legacy()
    except Exception:  # never block startup
        log.exception("Legacy rescore failed")
    stop = asyncio.Event()
    task = None
    if settings.scheduler_enabled:
        from .scheduler import loop

        task = asyncio.create_task(loop(stop))
    log.info("JobPilot AI %s ready (db=%s, llm=%s)", __version__, settings.database_url.split(":", 1)[0],
             "on" if settings.llm_enabled else "off")
    yield
    stop.set()
    if task:
        await task


def _rescore_legacy() -> None:
    """Scores saved before the ATS model lack keyword details; recompute them once."""
    from .db import session_scope
    from .models import MatchAssessment
    from .services.matching import score_jobs

    with session_scope() as db:
        users = {m.user_id for m in db.query(MatchAssessment).all() if "_keywords" not in (m.breakdown or {})}
    for uid in users:
        with session_scope() as db:
            n = score_jobs(db, uid)
            log.info("Rescored %s jobs for user %s with the ATS model", n, uid)


app = FastAPI(title="JobPilot AI", version=__version__, lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if not request.url.path.startswith("/api/docs"):
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        )
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    msgs = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e.get("loc", []) if x not in ("body", "query"))
        msgs.append(f"{loc}: {e.get('msg')}" if loc else e.get("msg"))
    return JSONResponse({"detail": "; ".join(msgs)}, status_code=422)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):  # never leak internals or secrets
    log.exception("Unhandled error")
    return JSONResponse({"detail": "Something went wrong on the server. Check the server log for details."}, status_code=500)


for r in (auth.router, profile.router, jobs.router, applications.router, network.router, misc.router, integrations.router):
    app.include_router(r)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")
