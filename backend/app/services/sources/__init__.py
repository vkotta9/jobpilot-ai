"""Job source adapters. Add a new source by subclassing `JobSourceAdapter`
and registering it in `ADAPTERS` — nothing else in the platform changes."""
from .base import JobSourceAdapter, NormalizedJob, SourceError
from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter
from .keyword import AdzunaAdapter, MuseAdapter, RemotiveAdapter
from .mock import MockAdapter

ADAPTERS: dict[str, type[JobSourceAdapter]] = {
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "mock": MockAdapter,
    "adzuna": AdzunaAdapter,
    "remotive": RemotiveAdapter,
    "muse": MuseAdapter,
}
KEYWORD_KINDS = ("adzuna", "remotive", "muse")

__all__ = ["ADAPTERS", "KEYWORD_KINDS", "JobSourceAdapter", "NormalizedJob", "SourceError"]
