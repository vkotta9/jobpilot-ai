"""Job source adapters. Add a new source by subclassing `JobSourceAdapter`
and registering it in `ADAPTERS` — nothing else in the platform changes."""
from .base import JobSourceAdapter, NormalizedJob, SourceError
from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter
from .mock import MockAdapter

ADAPTERS: dict[str, type[JobSourceAdapter]] = {
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "mock": MockAdapter,
}

__all__ = ["ADAPTERS", "JobSourceAdapter", "NormalizedJob", "SourceError"]
