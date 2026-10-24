"""Orchestrator background loop.

Runs in-process (asyncio) for the single-user MVP: every tick it finds users
whose scheduled search is due, unless automation is paused or the discovery
workflow is disabled, and runs discovery + matching in a worker thread. It only
*reads* job boards and writes to the local DB — it never submits applications
or sends messages. A per-user lock prevents overlapping runs (duplicate work).
For multi-node production, move `tick()` into a Celery beat task.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import timedelta

from .config import settings
from .db import session_scope
from .models import UserSettings, utcnow

log = logging.getLogger("jobpilot.scheduler")
_locks: dict[int, threading.Lock] = {}


def user_lock(user_id: int) -> threading.Lock:
    return _locks.setdefault(user_id, threading.Lock())


def tick() -> list[int]:
    from .services.discovery import run_all_sources

    ran = []
    with session_scope() as db:
        due = []
        for st in db.query(UserSettings).filter(UserSettings.automation_paused.is_(False)).all():
            if (st.workflows or {}).get("discovery") is False:
                continue
            if st.last_auto_search_at and st.last_auto_search_at > utcnow() - timedelta(hours=st.search_interval_hours):
                continue
            due.append(st.user_id)
    for uid in due:
        lock = user_lock(uid)
        if not lock.acquire(blocking=False):
            continue
        try:
            with session_scope() as db:
                st = db.get(UserSettings, uid)
                if st.automation_paused:  # re-check: user may have paused meanwhile
                    continue
                run_all_sources(db, uid)
                st.last_auto_search_at = utcnow()
            ran.append(uid)
        except Exception:  # pragma: no cover - logged, loop continues
            log.exception("Scheduled discovery failed for user %s", uid)
        finally:
            lock.release()
    return ran


async def loop(stop: asyncio.Event) -> None:
    log.info("Scheduler started (tick=%ss)", settings.scheduler_tick_s)
    while not stop.is_set():
        try:
            await asyncio.to_thread(tick)
        except Exception:  # pragma: no cover
            log.exception("Scheduler tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.scheduler_tick_s)
        except asyncio.TimeoutError:
            pass
