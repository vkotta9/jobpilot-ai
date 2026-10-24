"""Job source adapters. Add a new source by subclassing `JobSourceAdapter`
and registering it in `ADAPTERS` — nothing else in the platform changes."""
from .base import JobSourceAdapter, NormalizedJob, SourceError
from .companies import AshbyAdapter, RecruiteeAdapter, SmartRecruitersAdapter, WorkableAdapter
from .greenhouse import GreenhouseAdapter
from .keyword import (AdzunaAdapter, ArbeitnowAdapter, HimalayasAdapter, JobicyAdapter, JSearchAdapter, MuseAdapter,
                      RemotiveAdapter, USAJobsAdapter)
from .lever import LeverAdapter
from .mock import MockAdapter

ADAPTERS: dict[str, type[JobSourceAdapter]] = {
    # company career portals (identifier = the company's board slug)
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "ashby": AshbyAdapter,
    "smartrecruiters": SmartRecruitersAdapter,
    "workable": WorkableAdapter,
    "recruitee": RecruiteeAdapter,
    # keyword job search (identifier = "auto"; queries come from the profile)
    "remotive": RemotiveAdapter,
    "muse": MuseAdapter,
    "himalayas": HimalayasAdapter,
    "jobicy": JobicyAdapter,
    "arbeitnow": ArbeitnowAdapter,
    "jsearch": JSearchAdapter,
    "usajobs": USAJobsAdapter,
    "adzuna": AdzunaAdapter,
    # development only
    "mock": MockAdapter,
}
COMPANY_KINDS = ("greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee")
KEYWORD_KINDS = ("remotive", "muse", "himalayas", "jobicy", "arbeitnow", "jsearch", "usajobs", "adzuna")
FREE_DEFAULT_KINDS = ("remotive", "muse", "himalayas", "jobicy")

__all__ = ["ADAPTERS", "COMPANY_KINDS", "KEYWORD_KINDS", "FREE_DEFAULT_KINDS", "JobSourceAdapter", "NormalizedJob", "SourceError"]
