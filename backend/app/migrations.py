"""Tiny versioned migration runner.

Each migration is a function `(connection) -> None` registered in MIGRATIONS.
Applied versions are recorded in `schema_migrations`, so `python -m app.migrations`
is idempotent. Add new migrations by appending (never edit an applied one).
For a larger team, swap this for Alembic; the models are Alembic-compatible.
"""
from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from . import models  # noqa: F401  (register tables)
from .db import Base, engine

log = logging.getLogger("jobpilot.migrations")


def _m001_initial(conn: Connection) -> None:
    Base.metadata.create_all(bind=conn)


def _m002_resume_file_data(conn: Connection) -> None:
    cols = {c["name"] for c in inspect(conn).get_columns("resumes")}
    if "file_data" not in cols:
        coltype = "BYTEA" if conn.dialect.name == "postgresql" else "BLOB"
        conn.execute(text(f"ALTER TABLE resumes ADD COLUMN file_data {coltype}"))


def _m003_integrations(conn: Connection) -> None:
    models.IntegrationSetting.__table__.create(bind=conn, checkfirst=True)


def _m004_edu_status(conn: Connection) -> None:
    cols = {c["name"] for c in inspect(conn).get_columns("match_assessments")}
    if "edu_status" not in cols:
        conn.execute(text("ALTER TABLE match_assessments ADD COLUMN edu_status VARCHAR(20)"))


def _m005_job_triage(conn: Connection) -> None:
    cols = {c["name"] for c in inspect(conn).get_columns("jobs")}
    if "triage" not in cols:
        conn.execute(text("ALTER TABLE jobs ADD COLUMN triage VARCHAR(20)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_triage ON jobs (triage)"))
    if "triaged_at" not in cols:
        conn.execute(text("ALTER TABLE jobs ADD COLUMN triaged_at TIMESTAMP"))


def _m006_interview_prep(conn: Connection) -> None:
    cols = {c["name"] for c in inspect(conn).get_columns("applications")}
    if "prep" not in cols:
        conn.execute(text("ALTER TABLE applications ADD COLUMN prep JSON"))


MIGRATIONS: list[tuple[int, str, Callable[[Connection], None]]] = [
    (1, "initial schema", _m001_initial),
    (2, "store resume file bytes in database", _m002_resume_file_data),
    (3, "integration settings", _m003_integrations),
    (4, "education fit on match assessments", _m004_edu_status),
    (5, "job triage (skip / later)", _m005_job_triage),
    (6, "interview prep plans", _m006_interview_prep),
]


def run_migrations(eng=engine) -> list[int]:
    applied_now: list[int] = []
    with eng.begin() as conn:
        models.SchemaMigration.__table__.create(bind=conn, checkfirst=True)
        done = {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations"))}
        for version, name, fn in MIGRATIONS:
            if version in done:
                continue
            log.info("Applying migration %s: %s", version, name)
            fn(conn)
            conn.execute(
                text("INSERT INTO schema_migrations (version, name, applied_at) VALUES (:v, :n, CURRENT_TIMESTAMP)"),
                {"v": version, "n": name},
            )
            applied_now.append(version)
    return applied_now


def current_tables(eng=engine) -> list[str]:
    return sorted(inspect(eng).get_table_names())


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    applied = run_migrations()
    print(f"Applied migrations: {applied or 'none (up to date)'}")
    print("Tables:", ", ".join(current_tables()))
