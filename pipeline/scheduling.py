"""Runs a job once a day at a fixed time, such as the nightly file job at 02:00."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, time, timedelta, tzinfo
from typing import Optional

from .core import BackgroundProcess, Clock, Job

log = logging.getLogger(__name__)


def next_occurrence(after: float, at: time, tz: Optional[tzinfo] = None) -> float:
    """First epoch time strictly after `after` at which the clock in `tz` (local if None) reads `at`."""
    now = datetime.fromtimestamp(after, tz)
    candidate = datetime.combine(now.date(), at, tzinfo=now.tzinfo)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate.timestamp()


class DailyScheduler(BackgroundProcess):
    """Runs a job once a day at a fixed time. A failing run is logged; the schedule continues.
    Calculates the next run from the previous scheduled slot, so a slow job never causes a day to be skipped."""

    def __init__(self, job: Job, run_at: time, clock: Clock, tz: Optional[tzinfo] = None):
        self._job = job
        self._run_at = run_at
        self._clock = clock
        self._tz = tz

    def run(self, stop: threading.Event) -> None:
        next_run = next_occurrence(self._clock.now(), self._run_at, self._tz)
        while True:
            if self._clock.sleep(next_run - self._clock.now(), stop):
                return
            try:
                self._job.run()
            except Exception:
                log.exception("scheduled job %s failed", type(self._job).__name__)
            # Advance from the previous slot, not from "now", so a slow run doesn't skip a day.
            next_run = next_occurrence(next_run, self._run_at, self._tz)
