"""Testing one run per night at 02:00, failures don't stop the schedule."""
import threading
from datetime import datetime, time, timezone

import pytest

from pipeline.scheduling import DailyScheduler, next_occurrence
from tests.fakes import FakeClock, RecordingJob

UTC = timezone.utc
TWO_AM = time(2, 0)


def ts(text):
    return datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp()


@pytest.mark.parametrize("after, expected", [
    ("2026-01-01T12:00:00", "2026-01-02T02:00:00"),
    ("2026-01-01T01:00:00", "2026-01-01T02:00:00"),
    ("2026-01-01T02:00:00", "2026-01-02T02:00:00"),  # strictly after
])
def test_next_occurrence(after, expected):
    assert next_occurrence(ts(after), TWO_AM, UTC) == ts(expected)


def test_job_runs_once_per_day_at_configured_time():
    clock = FakeClock(ts("2026-01-01T12:00:00"))
    stop = threading.Event()
    job = RecordingJob(clock, stop=stop, stop_after=3)

    DailyScheduler(job, TWO_AM, clock, UTC).run(stop)

    assert job.run_times == [ts("2026-01-02T02:00:00"), ts("2026-01-03T02:00:00"), ts("2026-01-04T02:00:00")]


def test_failing_job_does_not_stop_the_schedule():
    clock = FakeClock(ts("2026-01-01T12:00:00"))
    stop = threading.Event()
    job = RecordingJob(clock, stop=stop, stop_after=2, fail_with=IOError("disk unavailable"))

    DailyScheduler(job, TWO_AM, clock, UTC).run(stop)

    assert len(job.run_times) == 2


def test_stopped_scheduler_does_not_run_job():
    clock = FakeClock(ts("2026-01-01T12:00:00"))
    stop = threading.Event()
    stop.set()
    job = RecordingJob(clock)

    DailyScheduler(job, TWO_AM, clock, UTC).run(stop)

    assert job.run_times == []
