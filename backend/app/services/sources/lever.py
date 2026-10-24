"""Lever Postings API (public, read-only, no credentials).

GET https://api.lever.co/v0/postings/{site}?mode=json
(EU accounts: https://api.eu.lever.co/v0/postings/{site}). Field reference:
https://github.com/lever/postings-api . Applying through the API requires an
employer-issued key, so JobPilot uses guided manual submission.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..textutil import strip_html
from .base import JobSourceAdapter, NormalizedJob, SourceError, infer_remote_type

API = "https://api.lever.co/v0/postings/{site}"
API_EU = "https://api.eu.lever.co/v0/postings/{site}"


class LeverAdapter(JobSourceAdapter):
    kind = "lever"
    docs_url = "https://github.com/lever/postings-api"

    def fetch(self) -> list[NormalizedJob]:
        site = self.identifier
        try:
            data = self._get_json(API.format(site=site), params={"mode": "json"})
        except SourceError as e:
            if e.status != 404:
                raise
            data = self._get_json(API_EU.format(site=site), params={"mode": "json"})
        if not isinstance(data, list):
            raise SourceError("lever: expected a JSON array of postings")
        company = self.company_name()
        return [self.normalize(self._lite(p, "text", ("description", "descriptionPlain", "lists", "additional", "additionalPlain")), company)
                for p in data if p.get("id") and p.get("text")]

    @staticmethod
    def normalize(p: dict, company: str) -> NormalizedJob:
        cats = p.get("categories") or {}
        parts = [p.get("descriptionPlain") or strip_html(p.get("description") or "")]
        for lst in p.get("lists") or []:
            parts.append(f"{lst.get('text', '')}:\n{strip_html(lst.get('content', ''))}")
        if p.get("additionalPlain"):
            parts.append(p["additionalPlain"])
        sr = p.get("salaryRange") or {}
        wt = (p.get("workplaceType") or "").lower()
        remote = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite"}.get(wt) or infer_remote_type(
            cats.get("location", ""), p.get("text", "")
        )
        created = p.get("createdAt")
        posted = (
            datetime.fromtimestamp(created / 1000, tz=timezone.utc).replace(tzinfo=None)
            if isinstance(created, (int, float)) else None
        )
        return NormalizedJob(
            external_id=str(p["id"]),
            title=str(p["text"]).strip(),
            company=company,
            location=cats.get("location", "") or ", ".join(cats.get("allLocations") or []),
            remote_type=remote,
            employment_type=cats.get("commitment", "") or "",
            department=cats.get("department", "") or cats.get("team", "") or "",
            description_text="\n\n".join(x for x in parts if x).strip(),
            salary_min=sr.get("min"),
            salary_max=sr.get("max"),
            salary_currency=sr.get("currency", "") or "",
            salary_interval=sr.get("interval", "") or "",
            posted_at=posted,
            url=p.get("hostedUrl", "") or "",
            apply_url=p.get("applyUrl", "") or p.get("hostedUrl", "") or "",
            raw={"id": p.get("id"), "createdAt": created},
        )
