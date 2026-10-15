"""Turns a Poisson message stream into 5-minute minibatches and hands them to dispatcher.

  Flow:
      PoissonMessageSource ─► MinibatchService ─► Dispatcher (e.g. WorkerPool)
                                   │
                                   └── TimeWindowAccumulator (batching rules)
"""
from __future__ import annotations

import itertools
import logging
import queue
import random
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator, Optional

from .core import BackgroundProcess, Clock, Dispatcher
from .distributions import Distribution, ExponentialDistribution

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Message:
    payload: str
    timestamp: float  # when the source emitted it; batch membership is decided by this
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True)
class MessageBatch:
    """Messages whose timestamps fall in time interval [window_start, window_end)."""

    messages: tuple[Message, ...]
    window_start: float
    window_end: float
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


class MessageSource(ABC):
    @abstractmethod
    def messages(self, stop: threading.Event) -> Iterator[Message]:
        """Yields messages until the source is exhausted or `stop` is set."""


class PoissonMessageSource(MessageSource):
    """Simulated source whose arrivals form a Poisson process (exponential gaps). Loops forever."""

    def __init__(self, interarrival_seconds: Distribution, clock: Clock):
        self._gaps = interarrival_seconds
        self._clock = clock

    @classmethod
    def with_rate_per_minute(cls, rate: float, clock: Clock,
                             rng: Optional[random.Random] = None) -> "PoissonMessageSource":
        return cls(ExponentialDistribution.from_rate(rate / 60.0, rng), clock)

    def messages(self, stop: threading.Event) -> Iterator[Message]:
        for seq in itertools.count(1):
            if self._clock.sleep(self._gaps.sample(), stop):
                return
            yield Message(f"message-{seq}", self._clock.now())


class TimeWindowAccumulator:
    """Pure batching rules, no threads or clocks.

    A batch is opened by its first message and holds every message stamped within
    `window_seconds` of it. A message stamped at or after the window end starts the next batch."""

    def __init__(self, window_seconds: float = 300.0):
        if not window_seconds > 0:
            raise ValueError("window must be positive")
        self._window = window_seconds
        self._open: list[Message] = []
        self._end: Optional[float] = None

    def add(self, message: Message) -> Optional[MessageBatch]:
        """Adds a message. Returns the previous batch if this message closed it."""
        closed = None
        if self._end is not None and message.timestamp >= self._end:
            closed = self._close()
        if self._end is None:
            self._end = message.timestamp + self._window
        self._open.append(message)
        return closed

    def poll(self, now: float) -> Optional[MessageBatch]:
        """Closes the open batch once its window has elapsed. 
        Enables batch closing even when no new message arrives."""
        if self._end is not None and now >= self._end:
            return self._close()
        return None

    def flush(self) -> Optional[MessageBatch]:
        """For use at shutdown. """
        return self._close() if self._open else None

    def seconds_until_close(self, now: float) -> Optional[float]:
        return None if self._end is None else max(0.0, self._end - now)

    def _close(self) -> MessageBatch:
        assert self._end is not None
        batch = MessageBatch(tuple(self._open), self._end - self._window, self._end)
        self._open, self._end = [], None
        return batch


_END = object()


class MinibatchService(BackgroundProcess):
    """Turns a message stream into minibatches and hands each one to the dispatcher.

    The source is read on its own thread into a buffer, so a batch closes on time even when
    no further messages arrive. Dispatching only enqueues, so forming the next batch never
    waits for earlier batches to be processed. On stop or source exhaustion the open batch is
    flushed."""

    def __init__(self, source: MessageSource, dispatcher: Dispatcher, clock: Clock,
                 window_seconds: float = 300.0, idle_poll_seconds: float = 0.5):
        self._source = source
        self._dispatcher = dispatcher
        self._clock = clock
        self._window = window_seconds
        self._idle_poll = idle_poll_seconds
        self._source_error: Optional[BaseException] = None

    def run(self, stop: threading.Event) -> None:
        buffer: queue.Queue = queue.Queue()
        threading.Thread(target=self._pump, args=(buffer, stop), name="minibatch-pump", daemon=True).start()
        accumulator = TimeWindowAccumulator(self._window)

        source_done = False
        while not stop.is_set():
            item = self._next(buffer, accumulator)
            if item is _END:
                source_done = True
                break
            if item is not None:
                self._emit(accumulator.add(item))
            self._emit(accumulator.poll(self._clock.now()))

        if not source_done:
            self._drain(buffer, accumulator)
        self._emit(accumulator.flush())

        if self._source_error is not None:
            raise RuntimeError("message source failed") from self._source_error

    def _next(self, buffer: queue.Queue, accumulator: TimeWindowAccumulator):
        remaining = accumulator.seconds_until_close(self._clock.now())
        timeout = self._idle_poll if remaining is None else min(max(remaining, 1e-3), self._idle_poll)
        try:
            return buffer.get(timeout=timeout)
        except queue.Empty:
            return None

    def _drain(self, buffer: queue.Queue, accumulator: TimeWindowAccumulator) -> None:
        while True:
            try:
                item = buffer.get_nowait()
            except queue.Empty:
                return
            if item is _END:
                return
            self._emit(accumulator.add(item))

    def _pump(self, buffer: queue.Queue, stop: threading.Event) -> None:
        try:
            for message in self._source.messages(stop):
                buffer.put(message)
        except BaseException as error:  # surfaced from run()
            log.exception("message source failed") # can be used in notifications
            self._source_error = error
        finally:
            buffer.put(_END)

    def _emit(self, batch: Optional[MessageBatch]) -> None:
        if batch is None:
            return
        log.info("minibatch %s: %d messages", batch.id[:8], len(batch.messages))
        self._dispatcher.dispatch(batch)
