"""Runtime configuration.

All secrets come from environment variables (optionally loaded from a local
`.env` file that is git-ignored). Nothing secret is ever stored in the database
or sent to the frontend.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
PROJECT_DIR = BASE_DIR.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines). Existing env vars win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(PROJECT_DIR / ".env")


def _normalize_db_url(url: str) -> str:
    """Hosts like Render/Heroku hand out postgres:// URLs; SQLAlchemy+psycopg3 needs postgresql+psycopg://."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(os.getenv("JOBPILOT_DATA_DIR", str(PROJECT_DIR / "data")))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_url = _normalize_db_url(os.getenv(
            "DATABASE_URL", f"sqlite:///{(self.data_dir / 'jobpilot.db').as_posix()}"
        ))
        self.upload_dir = self.data_dir / "uploads"
        self.export_dir = self.data_dir / "exports"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)

        # AI (optional). Without a key, deterministic fallbacks are used.
        self.openai_api_key = os.getenv("OPENAI_API_KEY") or None
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.llm_timeout_s = float(os.getenv("JOBPILOT_LLM_TIMEOUT", "45"))

        # Background automation
        self.scheduler_enabled = os.getenv("JOBPILOT_SCHEDULER", "1") == "1"
        self.scheduler_tick_s = int(os.getenv("JOBPILOT_SCHEDULER_TICK", "60"))
        self.source_pause_s = float(os.getenv("JOBPILOT_SOURCE_PAUSE", "0.5"))

        # Security
        self.session_days = int(os.getenv("JOBPILOT_SESSION_DAYS", "14"))
        self.max_upload_bytes = int(os.getenv("JOBPILOT_MAX_UPLOAD_MB", "5")) * 1024 * 1024
        # "1" = open, "0" = closed, "first" = only until the first account exists
        self.registration_mode = os.getenv("JOBPILOT_ALLOW_REGISTRATION", "1").strip().lower()

        # Development-only simulated job source (always labelled as SIMULATED in UI)
        self.allow_mock_sources = os.getenv("JOBPILOT_ALLOW_MOCK_SOURCES", "1") == "1"

        # HTTP for job sources
        self.http_timeout_s = float(os.getenv("JOBPILOT_HTTP_TIMEOUT", "20"))
        self.user_agent = os.getenv(
            "JOBPILOT_USER_AGENT", "JobPilotAI/0.1 (personal job-search assistant)"
        )

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key)


settings = Settings()
