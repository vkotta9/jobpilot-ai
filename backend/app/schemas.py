"""Pydantic request/response and structured-data schemas."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------- auth


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Enter a valid email address")
        return v


# ---------------------------------------------------------------- profile


class ExperienceItem(BaseModel):
    company: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=200)
    start: str = Field(default="", max_length=40)  # free text, e.g. "Jan 2021"
    end: str = Field(default="", max_length=40)  # "Present" allowed
    bullets: list[str] = Field(default_factory=list)


class EducationItem(BaseModel):
    institution: str = Field(default="", max_length=200)
    degree: str = Field(default="", max_length=200)
    field: str = Field(default="", max_length=200)
    start: str = ""
    end: str = ""
    details: str = ""


class ProjectItem(BaseModel):
    name: str = Field(default="", max_length=200)
    description: str = ""
    link: str = ""


class Preferences(BaseModel):
    target_titles: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    preferred_companies: list[str] = Field(default_factory=list)
    seniority: list[str] = Field(default_factory=list)  # e.g. ["mid", "senior"]
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: str = "USD"
    locations: list[str] = Field(default_factory=list)
    workplace: list[Literal["remote", "hybrid", "onsite"]] = Field(default_factory=list)
    employment_types: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)


class WorkAuthorization(BaseModel):
    authorized_countries: list[str] = Field(default_factory=list)
    requires_sponsorship: Optional[bool] = None  # None = not provided (never guessed)
    notes: str = ""


class MatchWeights(BaseModel):
    """Weights of the ATS match components (normalised; unknown legacy keys ignored)."""
    keywords: float = Field(default=45, ge=0, le=100)
    title: float = Field(default=15, ge=0, le=100)
    experience: float = Field(default=15, ge=0, le=100)
    education: float = Field(default=15, ge=0, le=100)
    soft_skills: float = Field(default=10, ge=0, le=100)


class ProfileIn(BaseModel):
    full_name: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=320)
    phone: str = Field(default="", max_length=64)
    location: str = Field(default="", max_length=200)
    headline: str = Field(default="", max_length=300)
    summary: str = Field(default="", max_length=5000)
    links: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    preferences: Preferences = Field(default_factory=Preferences)
    work_authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)
    match_weights: MatchWeights = Field(default_factory=MatchWeights)
    confirm: bool = False  # user explicitly confirms the profile is accurate


class ProfilePatch(BaseModel):
    """Partial update: only provided fields change, nothing else is lost."""

    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    headline: Optional[str] = None
    summary: Optional[str] = None
    links: Optional[list[str]] = None
    skills: Optional[list[str]] = None
    experience: Optional[list[ExperienceItem]] = None
    education: Optional[list[EducationItem]] = None
    certifications: Optional[list[str]] = None
    projects: Optional[list[ProjectItem]] = None
    preferences: Optional[Preferences] = None
    work_authorization: Optional[WorkAuthorization] = None
    match_weights: Optional[MatchWeights] = None
    confirm: bool = False


# ---------------------------------------------------------------- jobs


class SourceIn(BaseModel):
    kind: Literal["greenhouse", "lever", "mock", "adzuna", "remotive", "muse"]
    identifier: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.\-]+$")
    display_name: str = Field(default="", max_length=200)


class ManualJobIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    company: str = Field(min_length=1, max_length=200)
    location: str = ""
    url: str = Field(default="", max_length=1000)
    description_text: str = Field(default="", max_length=100_000)
    remote_type: Literal["remote", "hybrid", "onsite", "unknown"] = "unknown"
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None


class SavedSearchIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    filters: dict = Field(default_factory=dict)


# ---------------------------------------------------------------- documents / apps


class DocumentEdit(BaseModel):
    content: dict


class StatusChange(BaseModel):
    status: str
    detail: str = Field(default="", max_length=2000)


class ApplicationPatch(BaseModel):
    notes: Optional[str] = None
    next_action: Optional[str] = None
    follow_up_at: Optional[str] = None  # ISO date/datetime, "" to clear
    last_contact_at: Optional[str] = None
    outcome_detail: Optional[str] = None


class ApproveIn(BaseModel):
    confirm: bool = False


class SubmissionRecord(BaseModel):
    confirm: bool = False
    method: Literal["manual_user_submitted"] = "manual_user_submitted"
    confirmation_detail: str = Field(default="", max_length=4000)


class QuestionsIn(BaseModel):
    questions: list[str] = Field(min_length=1, max_length=50)


class AnswerEdit(BaseModel):
    answer: str = Field(max_length=10_000)
    approve: bool = False
    reusable: bool = False


class InterviewIn(BaseModel):
    stage: str = Field(min_length=1, max_length=100)
    scheduled_at: Optional[str] = None
    notes: str = ""
    outcome: str = "pending"


# ---------------------------------------------------------------- networking


class ContactIn(BaseModel):
    job_id: Optional[int] = None
    name: str = Field(min_length=1, max_length=200)
    role: str = ""
    company: str = ""
    contact_type: Literal["recruiter", "hiring_manager", "team_member", "department_leader", "other"] = "other"
    source_url: str = Field(default="", max_length=1000)
    verified: bool = False
    relevance: str = ""
    email: str = ""
    notes: str = ""


class OutreachGenerateIn(BaseModel):
    channel: Literal["linkedin", "email"] = "linkedin"
    kind: Literal["connection", "outreach", "follow_up"] = "connection"


class OutreachEdit(BaseModel):
    body: Optional[str] = None
    subject: Optional[str] = None


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_at: str
    application_id: Optional[int] = None


class SettingsIn(BaseModel):
    automation_paused: Optional[bool] = None
    search_interval_hours: Optional[int] = Field(default=None, ge=1, le=24 * 30)
    high_match_threshold: Optional[int] = Field(default=None, ge=0, le=100)
    follow_up_days: Optional[int] = Field(default=None, ge=1, le=90)
    workflows: Optional[dict[str, bool]] = None
