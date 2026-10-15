"""Core abstractions (Clock, Dispatcher, Processor, Job, BackgroundProcess) that the rest of the
pipeline depends on, so implementations can be swapped in main.py (Dependency Inversion)."""
from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from typing import Any


class Clock(ABC):
    """Current time and interruptible sleep. SystemClock in production; tests use a fake
    clock, so they never wait for real minutes."""

    @abstractmethod
    def now(self) -> float:
        """Current time in seconds since the Unix epoch."""

    @abstractmethod
    def sleep(self, seconds: float, stop: threading.Event) -> bool:
        """Waits for `seconds`. Returns True if `stop` was set, meaning the caller should exit."""


class SystemClock(Clock):
    def now(self) -> float:
        return time.time()

    def sleep(self, seconds: float, stop: threading.Event) -> bool:
        return stop.wait(max(0.0, seconds))


class Dispatcher(ABC):
    @abstractmethod
    def dispatch(self, item: Any) -> None:
        """Accepts work without waiting for it to be processed (e.g. WorkerPool)."""


class Processor(ABC):
    @abstractmethod
    def process(self, item: Any) -> None:
        """Does the actual work for one item. Runs on a worker thread."""


class Job(ABC):
    """A single finite run, such as the nightly file job, typically triggered by a scheduler."""

    @abstractmethod
    def run(self) -> Any: ...


class BackgroundProcess(ABC):
    """A long-running loop that stops when its stop event is set."""

    @abstractmethod
    def run(self, stop: threading.Event) -> None: ...
