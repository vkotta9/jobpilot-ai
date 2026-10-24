"""Symmetric encryption for API keys users save in the app.

The key comes from JOBPILOT_SECRET_KEY if set; otherwise it is derived from
DATABASE_URL (whose password is not stored in the database itself); for a
local SQLite database a random key file is created in the data directory.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings

_fernet = None


def _key_material() -> bytes:
    env = os.getenv("JOBPILOT_SECRET_KEY")
    if env:
        return env.encode()
    if not settings.database_url.startswith("sqlite"):
        return ("jobpilot:" + settings.database_url).encode()
    path = settings.data_dir / "secret.key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48))
        os.chmod(path, 0o600)
    return path.read_text().strip().encode()


def _f() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(_key_material()).digest()))
    return _fernet


def seal(data: dict) -> str:
    return _f().encrypt(json.dumps(data).encode()).decode()


def unseal(token: str) -> dict:
    try:
        return json.loads(_f().decrypt(token.encode()))
    except (InvalidToken, ValueError):
        return {}


def mask(value: str) -> str:
    if not value:
        return ""
    return "••••" + value[-4:] if len(value) > 8 else "••••"
