"""Test doubles for the data processing pipeline."""
from __future__ import annotations

import queue
import random
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterable, Iterator, Optional

from pipeline.bucketing import BucketingStrategy
from pipeline.core import BackgroundProcess, Clock, Dispatcher, Job, Processor
from pipeline.distributions import Distribution, ExponentialDistribution
from pipeline.files import MB, FileBucket, FileDescriptor, FileSource, SimulatedFileSource
from pipeline.messaging import Message, MessageSource


def wait_until(condition: Callable[[], bool], timeout: float = 3.0) -> None:
    """Polls until `condition` holds; for state changed by background threads."""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition was not met in time")
        time.sleep(0.005)


@contextmanager
def running(process: BackgroundProcess) -> Iterator[threading.Event]:
    """Runs a background process on a thread; stops it and re-raises its errors on exit."""
    stop = threading.Event()
    errors: list[BaseException] = []

    def target() -> None:
        try:
            process.run(stop)
        except BaseException as e:
            errors.append(e)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    try:
        yield stop
    finally:
        stop.set()
        thread.join(5)
        assert not thread.is_alive(), "process did not stop"
        if errors:
            raise errors[0]


# ---------- Time ----------
class FakeClock(Clock):
    """Time only moves when the test says so. sleep() advances time instantly."""

    def __init__(self, start: float = 0.0):
        self._t = start
        self._lock = threading.Lock()

    def now(self) -> float:
        with self._lock:
            return self._t

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._t += seconds

    def sleep(self, seconds: float, stop: threading.Event) -> bool:
        if stop.is_set():
            return True
        self.advance(max(0.0, seconds))
        return stop.is_set()


# ---------- Message sources ----------
class ManualMessageSource(MessageSource):
    """Mock source driven by the test. Messages are stamped with the (fake) clock."""

    def __init__(self, clock: Clock):
        self._clock = clock
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._emitted = 0
        self._delivered = 0

    @property
    def delivered(self) -> int:
        with self._lock:
            return self._delivered

    def emit(self, payload: str, wait: bool = True) -> None:
        """Emits a message; with wait=True blocks until the consumer has fully taken it."""
        with self._lock:
            self._emitted += 1
            target = self._emitted
        self._queue.put(Message(payload, self._clock.now()))
        if wait:
            wait_until(lambda: self.delivered >= target)

    def complete(self) -> None:
        self._queue.put(None)

    def messages(self, stop: threading.Event) -> Iterator[Message]:
        while not stop.is_set():
            try:
                message = self._queue.get(timeout=0.01)
            except queue.Empty:
                continue
            if message is None:
                return
            yield message
            # Resumes only when the consumer asks for the next message, i.e. after it handled this one.
            with self._lock:
                self._delivered += 1


class FailingMessageSource(MessageSource):
    def messages(self, stop: threading.Event) -> Iterator[Message]:
        raise IOError("connection lost")
        yield  # pragma: no cover  (makes this a generator)


# ---------- Distributions ----------
class SequenceDistribution(Distribution):
    """Stub returning scripted values in order, cycling when exhausted."""

    def __init__(self, *values: float):
        self._values = values
        self._i = 0

    def sample(self) -> float:
        value = self._values[self._i % len(self._values)]
        self._i += 1
        return value


# ---------- Files ----------
class InMemoryFileSource(FileSource):
    """Mock file source returning a fixed list; counts how often it was asked."""

    def __init__(self, files: Iterable[FileDescriptor]):
        self._files = list(files)
        self.gather_count = 0

    def gather(self) -> list[FileDescriptor]:
        self.gather_count += 1
        return list(self._files)


def files_of_sizes_mb(*sizes_mb: float) -> list[FileDescriptor]:
    return [FileDescriptor(f"file-{i}.dat", int(size * MB)) for i, size in enumerate(sizes_mb, start=1)]


def exponential_files(count: int, mean_bytes: float, seed: int) -> list[FileDescriptor]:
    """Reproducible mock file set with exponentially distributed sizes."""
    return SimulatedFileSource(ExponentialDistribution(mean_bytes, random.Random(seed)), count).gather()


class StubBucketingStrategy(BucketingStrategy):
    """Spy: records its inputs and returns predefined buckets."""

    def __init__(self, result: list[FileBucket]):
        self._result = result
        self.received_files: Optional[list[FileDescriptor]] = None
        self.received_capacity: Optional[int] = None

    def pack(self, files: Iterable[FileDescriptor], capacity_bytes: int) -> list[FileBucket]:
        self.received_files = list(files)
        self.received_capacity = capacity_bytes
        return self._result


# ---------- Dispatchers / processors / jobs ----------
class RecordingDispatcher(Dispatcher):
    """Mock dispatcher that records everything dispatched to it."""

    def __init__(self) -> None:
        self._items: list[Any] = []
        self._lock = threading.Lock()

    @property
    def items(self) -> list[Any]:
        with self._lock:
            return list(self._items)

    def dispatch(self, item: Any) -> None:
        with self._lock:
            self._items.append(item)

    def wait_for(self, count: int) -> list[Any]:
        wait_until(lambda: len(self.items) >= count)
        return self.items


class RecordingProcessor(Processor):
    def __init__(self) -> None:
        self._items: list[Any] = []
        self._lock = threading.Lock()

    @property
    def processed(self) -> list[Any]:
        with self._lock:
            return list(self._items)

    def process(self, item: Any) -> None:
        with self._lock:
            self._items.append(item)


class GatedProcessor(Processor):
    """Blocks every item until release(); tracks concurrency."""

    def __init__(self) -> None:
        self._gate = threading.Event()
        self._lock = threading.Lock()
        self.started = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self.completed = 0

    def process(self, item: Any) -> None:
        with self._lock:
            self.started += 1
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            self._gate.wait(10)
        finally:
            with self._lock:
                self.in_flight -= 1
                self.completed += 1

    def release(self) -> None:
        self._gate.set()


class RecordingJob(Job):
    """Records run times; can fail every run and/or set `stop` after N runs."""

    def __init__(self, clock: Clock, stop: Optional[threading.Event] = None, stop_after: Optional[int] = None,
                 fail_with: Optional[Exception] = None):
        self._clock = clock
        self._stop = stop
        self._stop_after = stop_after
        self._fail_with = fail_with
        self.run_times: list[float] = []

    def run(self) -> None:
        self.run_times.append(self._clock.now())
        if self._stop is not None and self._stop_after is not None and len(self.run_times) >= self._stop_after:
            self._stop.set()
        if self._fail_with is not None:
            raise self._fail_with
