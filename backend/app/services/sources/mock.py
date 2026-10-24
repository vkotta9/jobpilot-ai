"""SIMULATED development source.

Produces clearly fake listings (company names end in "(Demo)", URLs point to
example.com, and every row is stored with is_simulated=True and badged in the
UI). Exists only so the full workflow can be tried without network access.
Disable with JOBPILOT_ALLOW_MOCK_SOURCES=0.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .base import JobSourceAdapter, NormalizedJob

_SAMPLES = [
    ("Senior Backend Engineer", "Remote - US", "remote", 150000, 190000,
     "We are looking for a Senior Backend Engineer with 5+ years of experience building APIs in Python "
     "(FastAPI or Django), PostgreSQL, Redis, Docker and AWS. Experience with Kafka and Kubernetes is a plus. "
     "You will design distributed systems, mentor engineers and own CI/CD. We are unable to sponsor visas for this role."),
    ("Machine Learning Engineer", "New York, NY", "hybrid", 160000, 210000,
     "Build and deploy machine learning models with PyTorch, scikit-learn and Python. 3+ years of experience "
     "with MLOps, Docker, AWS or GCP, SQL and data pipelines (Airflow, Spark). LLM and RAG experience preferred."),
    ("Full Stack Developer", "Austin, TX", "onsite", 110000, 140000,
     "Full stack developer with React, TypeScript, Node.js and PostgreSQL. 2+ years of experience. "
     "Familiarity with GraphQL, REST APIs, testing and Agile practices."),
    ("Data Analyst", "Remote", "remote", 85000, 105000,
     "Data Analyst skilled in SQL, Excel, Tableau or Power BI, and Python (pandas). Communicate insights to "
     "stakeholders, run A/B testing analysis. 2+ years of experience."),
    ("Staff Platform Engineer", "San Francisco, CA", "hybrid", None, None,
     "Staff engineer for our platform team: Kubernetes, Terraform, AWS, Go, observability (Prometheus, Grafana). "
     "8+ years of experience leading infrastructure projects and system design."),
]


class MockAdapter(JobSourceAdapter):
    kind = "mock"
    is_simulated = True

    def company_name(self) -> str:
        return f"{super().company_name()} (Demo)"

    def fetch(self) -> list[NormalizedJob]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        comp = self.company_name()
        out = []
        for i, (title, loc, remote, smin, smax, desc) in enumerate(_SAMPLES):
            ext = f"{self.identifier}-{i}"
            out.append(NormalizedJob(
                external_id=ext, title=title, company=comp, location=loc, remote_type=remote,
                employment_type="Full-time", department="Engineering",
                description_text="[SIMULATED LISTING — not a real job]\n\n" + desc,
                salary_min=smin, salary_max=smax, salary_currency="USD" if smin else "",
                salary_interval="per-year-salary" if smin else "",
                posted_at=now - timedelta(days=i * 2),
                url=f"https://example.com/demo-jobs/{ext}", apply_url=f"https://example.com/demo-jobs/{ext}/apply",
            ))
        return out
