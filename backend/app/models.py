"""Database schema.

Every private table carries `user_id` and every query in the API layer is
filtered by the authenticated user (see `security.owned`). Profile sub-records
(experience, education, ...) are stored as validated JSON on the profile for the
MVP; they are only ever written through the Profile service, which validates
them with Pydantic schemas.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    LargeBinary,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Pipeline statuses (Feature G). Order matters for analytics/kanban.
PIPELINE_STATUSES = [
    "discovered",
    "shortlisted",
    "preparing",
    "awaiting_approval",
    "applied",
    "assessment",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
]


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class UserSettings(Base):
    __tablename__ = "user_settings"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    automation_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    search_interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    high_match_threshold: Mapped[int] = mapped_column(Integer, default=75)
    follow_up_days: Mapped[int] = mapped_column(Integer, default=7)
    # per-workflow toggles: {"discovery": true, "follow_up_tasks": true, "digest": true}
    workflows: Mapped[dict] = mapped_column(JSON, default=dict)
    last_auto_search_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    full_name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    headline: Mapped[str] = mapped_column(String(300), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    links: Mapped[list] = mapped_column(JSON, default=list)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    experience: Mapped[list] = mapped_column(JSON, default=list)
    education: Mapped[list] = mapped_column(JSON, default=list)
    certifications: Mapped[list] = mapped_column(JSON, default=list)
    projects: Mapped[list] = mapped_column(JSON, default=list)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    work_authorization: Mapped[dict] = mapped_column(JSON, default=dict)
    match_weights: Mapped[dict] = mapped_column(JSON, default=dict)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ProfileRevision(Base):
    """Snapshot of the profile before each update, so nothing is ever lost."""

    __tablename__ = "profile_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Resume(Base):
    """Uploaded master resumes. Immutable once stored; a new upload = new row."""

    __tablename__ = "resumes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    file_data: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True, deferred=True)
    text: Mapped[str] = mapped_column(Text, default="")
    parsed: Mapped[dict] = mapped_column(JSON, default=dict)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("user_id", "sha256", name="uq_resume_user_hash"),)


class JobSource(Base):
    __tablename__ = "job_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # greenhouse | lever | mock
    identifier: Mapped[str] = mapped_column(String(200))  # board token / site name
    display_name: Mapped[str] = mapped_column(String(200), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(40), default="never_run")
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_job_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("user_id", "kind", "identifier", name="uq_source"),)


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("job_sources.id", ondelete="SET NULL"), nullable=True
    )
    source_kind: Mapped[str] = mapped_column(String(40))
    external_id: Mapped[str] = mapped_column(String(200))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    duplicate_of_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(300), default="")
    remote_type: Mapped[str] = mapped_column(String(20), default="unknown")  # remote|hybrid|onsite|unknown
    employment_type: Mapped[str] = mapped_column(String(60), default="")
    department: Mapped[str] = mapped_column(String(200), default="")
    description_text: Mapped[str] = mapped_column(Text, default="")
    salary_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    salary_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(10), default="")
    salary_interval: Mapped[str] = mapped_column(String(30), default="")
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    url: Mapped[str] = mapped_column(String(1000), default="")
    apply_url: Mapped[str] = mapped_column(String(1000), default="")
    listing_status: Mapped[str] = mapped_column(String(20), default="active")  # active|closed
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)

    application: Mapped[Optional["Application"]] = relationship(
        back_populates="job", uselist=False, cascade="all, delete-orphan"
    )
    __table_args__ = (
        UniqueConstraint("user_id", "source_kind", "external_id", name="uq_job_source_ext"),
        Index("ix_jobs_user_status", "user_id", "listing_status"),
    )


class JobSnapshot(Base):
    """History of a listing whenever its content changes."""

    __tablename__ = "job_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    content_hash: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)


class MatchAssessment(Base):
    __tablename__ = "match_assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    score: Mapped[int] = mapped_column(Integer)
    recommendation: Mapped[str] = mapped_column(String(20))  # apply|review|skip
    breakdown: Mapped[dict] = mapped_column(JSON)
    matched_skills: Mapped[list] = mapped_column(JSON, default=list)
    missing_skills: Mapped[list] = mapped_column(JSON, default=list)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")
    weights: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Application(Base):
    """The tracker record for one job (created when a job is shortlisted)."""

    __tablename__ = "applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(30), default="shortlisted")
    resume_doc_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    cover_letter_doc_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    approved_package_hash: Mapped[str] = mapped_column(String(64), default="")
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    submission_method: Mapped[str] = mapped_column(String(40), default="")
    submission_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmation_detail: Mapped[str] = mapped_column(Text, default="")
    follow_up_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_contact_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    next_action: Mapped[str] = mapped_column(String(300), default="")
    outcome_detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    job: Mapped[Job] = relationship(back_populates="application", foreign_keys=[job_id])
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_application_job"),)


class Document(Base):
    """Tailored resumes and cover letters (versioned, per job)."""

    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # resume | cover_letter
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[dict] = mapped_column(JSON)  # structured resume or {"body": "..."}
    flags: Mapped[list] = mapped_column(JSON, default=list)  # items needing confirmation
    generator: Mapped[str] = mapped_column(String(40), default="deterministic")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("job_id", "kind", "version", name="uq_doc_version"),)


class ScreeningAnswer(Base):
    __tablename__ = "screening_answers"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True
    )
    question: Mapped[str] = mapped_column(Text)
    question_key: Mapped[str] = mapped_column(String(300), index=True)
    category: Mapped[str] = mapped_column(String(40), default="general")
    answer: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # needs_input|draft|approved
    source: Mapped[str] = mapped_column(String(200), default="")
    reusable: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(200), default="")
    company: Mapped[str] = mapped_column(String(200), default="")
    contact_type: Mapped[str] = mapped_column(String(40), default="other")
    source_url: Mapped[str] = mapped_column(String(1000), default="")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    relevance: Mapped[str] = mapped_column(Text, default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    last_contacted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OutreachMessage(Base):
    __tablename__ = "outreach_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    channel: Mapped[str] = mapped_column(String(20))  # linkedin | email
    kind: Mapped[str] = mapped_column(String(20))  # connection | outreach | follow_up
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved|sent
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FollowUpTask(Base):
    __tablename__ = "follow_up_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=True
    )
    contact_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(40), default="custom")
    dedupe_key: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(300))
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (Index("ix_task_dedupe", "user_id", "dedupe_key"),)


class Interview(Base):
    __tablename__ = "interviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(100))
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(String(40), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ApplicationEvent(Base):
    __tablename__ = "application_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str] = mapped_column(String(30), default="")
    to_status: Mapped[str] = mapped_column(String(30), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IntegrationSetting(Base):
    """Per-user connection settings (API keys) — stored encrypted (services/secretbox.py)."""

    __tablename__ = "integration_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40))  # ai | adzuna | muse
    data_encrypted: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_integration_provider"),)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(60), default="")
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


def to_dict(obj: Any, exclude: tuple[str, ...] = ()) -> dict:
    out = {}
    for col in obj.__table__.columns:
        if col.name in exclude or col.name in ("file_data", "data_encrypted"):
            continue
        val = getattr(obj, col.name)
        if isinstance(val, datetime):
            val = val.isoformat() + "Z"
        out[col.name] = val
    return out
