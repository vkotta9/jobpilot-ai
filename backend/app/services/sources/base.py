"""Adapter contract + shared HTTP handling (timeouts, retries, rate limits)."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

import httpx

from ...config import settings

log = logging.getLogger("jobpilot.sources")


class SourceError(Exception):
    """A user-presentable error from a job source."""

    def __init__(self, message: str, *, retryable: bool = False, status: Optional[int] = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@dataclass
class NormalizedJob:
    external_id: str
    title: str
    company: str
    location: str = ""
    remote_type: str = "unknown"  # remote|hybrid|onsite|unknown
    employment_type: str = ""
    department: str = ""
    description_text: str = ""
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: str = ""
    salary_interval: str = ""
    posted_at: Optional[datetime] = None
    url: str = ""
    apply_url: str = ""
    raw: dict = field(default_factory=dict, repr=False)


class JobSourceAdapter:
    kind: str = "base"
    is_simulated: bool = False
    requires_credentials: bool = False
    docs_url: str = ""

    keyword = False
    label = ""
    min_interval_hours = 0

    @classmethod
    def interval_for(cls, identifier: str) -> int:
        '''Minimum hours between runs for this source (some free plans allow few requests).'''
        return cls.min_interval_hours

    def __init__(self, identifier: str, *, transport: Optional[httpx.BaseTransport] = None,
                 sleep: Callable[[float], None] = time.sleep, context: Optional[dict] = None):
        self.identifier = identifier
        self._transport = transport
        self._sleep = sleep

    # -- override
    def fetch(self) -> list[NormalizedJob]:  # pragma: no cover - abstract
        raise NotImplementedError

    def company_name(self) -> str:
        return self.identifier.replace("-", " ").replace("_", " ").title()

    # -- shared HTTP with bounded retries
    timeout_s: Optional[float] = None

    def _get_json_headers(self, url: str, params: dict, headers: dict, max_attempts: int = 2) -> Any:
        self._extra_headers = headers
        try:
            return self._get_json(url, params=params, max_attempts=max_attempts)
        finally:
            self._extra_headers = {}

    def _post_json(self, url: str, body: dict, max_attempts: int = 2) -> Any:
        self._post_body = body
        try:
            return self._get_json(url, max_attempts=max_attempts)
        finally:
            self._post_body = None

    def _get_json(self, url: str, params: Optional[dict] = None, max_attempts: int = 3) -> Any:
        last_err: Optional[SourceError] = None
        headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
        headers.update(getattr(self, "_extra_headers", {}) or {})
        with httpx.Client(timeout=self.timeout_s or settings.http_timeout_s, transport=self._transport,
                          headers=headers, follow_redirects=True) as client:
            for attempt in range(1, max_attempts + 1):
                try:
                    body = getattr(self, "_post_body", None)
                    resp = client.post(url, json=body) if body is not None else client.get(url, params=params)
                except httpx.TimeoutException:
                    last_err = SourceError(f"{self.kind}: request timed out", retryable=True)
                except httpx.HTTPError as e:
                    last_err = SourceError(f"{self.kind}: network error ({e.__class__.__name__})", retryable=True)
                else:
                    if resp.status_code == 404:
                        raise SourceError(
                            (f"{self.kind}: the service's search address wasn't found (404)." if self.keyword else
                             f"{self.kind}: board '{self.identifier}' not found (404). Check the board token / site name."),
                            status=404,
                        )
                    if resp.status_code == 429:
                        wait = min(float(resp.headers.get("retry-after", "5") or 5), 30)
                        last_err = SourceError(f"{self.kind}: rate limited (429)", retryable=True, status=429)
                        if attempt < max_attempts:
                            self._sleep(wait)
                        continue
                    if resp.status_code in (401, 403):
                        raise SourceError(f"{self.kind}: access denied ({resp.status_code})", status=resp.status_code)
                    if resp.status_code >= 500:
                        last_err = SourceError(f"{self.kind}: server error {resp.status_code}", retryable=True,
                                               status=resp.status_code)
                    elif resp.status_code >= 400:
                        raise SourceError(f"{self.kind}: request rejected ({resp.status_code})", status=resp.status_code)
                    else:
                        ctype = resp.headers.get("content-type", "")
                        if "json" not in ctype:
                            # Lever occasionally serves HTML even with mode=json
                            last_err = SourceError(f"{self.kind}: unexpected non-JSON response", retryable=True)
                        else:
                            try:
                                return resp.json()
                            except ValueError:
                                last_err = SourceError(f"{self.kind}: invalid JSON", retryable=True)
                if attempt < max_attempts:
                    self._sleep(min(2 ** attempt, 10))
        assert last_err is not None
        raise last_err


def infer_remote_type(*texts: str) -> str:
    joined = " ".join(t for t in texts if t).lower()
    if "hybrid" in joined:
        return "hybrid"
    if "remote" in joined or "anywhere" in joined or "work from home" in joined:
        return "remote"
    if joined.strip():
        return "onsite"
    return "unknown"
