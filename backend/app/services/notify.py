"""Email notifications.

Render's free plan blocks outbound SMTP, so JobPilot sends email through Resend's HTTPS API (free: 3,000 emails a
month, 100 a day). Without your own domain, Resend sends from onboarding@resend.dev and only to the email address of
your Resend account — fine for alerts to yourself. Self-hosted servers can use SMTP instead (JOBPILOT_SMTP_* env vars).
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Optional

import httpx

from ..config import settings

log = logging.getLogger("jobpilot.notify")
PUBLIC_URL = {"value": os.getenv("JOBPILOT_PUBLIC_URL", "").rstrip("/")}  # set from incoming requests when unset


class EmailError(Exception):
    pass


def email_config(db, user_id: int) -> Optional[dict]:
    from ..models import IntegrationSetting
    from .secretbox import unseal

    row = db.query(IntegrationSetting).filter_by(user_id=user_id, provider="email").one_or_none()
    data = unseal(row.data_encrypted) if row else {}
    if data.get("resend_key") and data.get("to"):
        return data
    if os.getenv("JOBPILOT_SMTP_HOST") and data.get("to"):
        return {"smtp": True, **data}
    return None


def send_email(cfg: dict, subject: str, html: str, text: str, transport: Optional[httpx.BaseTransport] = None) -> str:
    """Send one email to cfg['to']. Returns the provider's message id (or 'smtp')."""
    to = cfg["to"]
    if cfg.get("resend_key"):
        sender = cfg.get("from") or "JobPilot <onboarding@resend.dev>"
        try:
            with httpx.Client(timeout=20, transport=transport) as c:
                r = c.post("https://api.resend.com/emails",
                           headers={"Authorization": f"Bearer {cfg['resend_key']}", "Content-Type": "application/json",
                                    "User-Agent": settings.user_agent},
                           json={"from": sender, "to": [to], "subject": subject, "html": html, "text": text})
        except httpx.HTTPError as e:
            raise EmailError(f"Couldn't reach Resend ({e.__class__.__name__}).")
        if r.status_code in (401, 403):
            msg = ""
            try:
                msg = r.json().get("message", "")
            except ValueError:
                pass
            if "own email" in msg.lower() or "testing emails" in msg.lower():
                raise EmailError("Resend only sends test emails to the address you signed up to Resend with — "
                                 "set 'Send alerts to' to that address (or verify a domain in Resend).")
            raise EmailError("Resend rejected the API key — check it in Settings → Connections.")
        if r.status_code == 429:
            raise EmailError("Resend's daily limit was reached (100 emails/day on the free plan).")
        if r.status_code >= 400:
            raise EmailError(f"Resend returned HTTP {r.status_code}.")
        return (r.json() or {}).get("id", "sent")
    if cfg.get("smtp"):
        msg = EmailMessage()
        msg["Subject"], msg["To"] = subject, to
        msg["From"] = os.getenv("JOBPILOT_SMTP_FROM", os.getenv("JOBPILOT_SMTP_USER", ""))
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        try:
            with smtplib.SMTP(os.environ["JOBPILOT_SMTP_HOST"], int(os.getenv("JOBPILOT_SMTP_PORT", "587")), timeout=20) as s:
                s.starttls()
                if os.getenv("JOBPILOT_SMTP_USER"):
                    s.login(os.environ["JOBPILOT_SMTP_USER"], os.getenv("JOBPILOT_SMTP_PASSWORD", ""))
                s.send_message(msg)
        except (OSError, smtplib.SMTPException) as e:
            raise EmailError(f"SMTP failed ({e.__class__.__name__}).")
        return "smtp"
    raise EmailError("Email isn't set up — add a Resend key in Settings → Connections.")
