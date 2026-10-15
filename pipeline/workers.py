"""Runs work on a fixed pool of worker threads and routes each item to the right processor."""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .core import Dispatcher, Processor

log = logging.getLogger(__name__)


class WorkerPool(Dispatcher):
    """Fixed number of worker threads. `dispatch` only enqueues, so producers such as the minibatch service 
    never wait for processing. A failing item is logged and does not affect other items; after shutdown(), 
    new work is rejected. Wraps a ThreadPoolExecutor."""

    def __init__(self, processor: Processor, workers: int = 10):
        if workers <= 0:
            raise ValueError("workers must be positive")
        self._processor = processor
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="worker")
        self._lock = threading.Lock()
        self._closed = False
        self.workers = workers

    def dispatch(self, item: Any) -> None:
        """Calls submit and returns immediately."""
        with self._lock:
            if self._closed:
                raise RuntimeError("worker pool is shut down")
            self._executor.submit(self._safe_process, item)

    def shutdown(self, wait: bool = True) -> None:
        """Stops accepting work; with wait=True, blocks until queued work is done."""
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=wait)

    def __enter__(self) -> "WorkerPool":
        return self

    def __exit__(self, *exc: object) -> None:
        self.shutdown()

    def _safe_process(self, item: Any) -> None:
        try:
            self._processor.process(item)
        except Exception:
            log.exception("processing of %r failed", item)


class WorkItemRouter(Processor):
    """Lets one pool serve several kinds of work: each item goes to the processor registered
    for its type (MessageBatch or FileBucket). New work types are added by registration, 
    not by editing the pool."""

    def __init__(self) -> None:
        self._processors: dict[type, Callable[[Any], None]] = {}

    def register(self, item_type: type, processor: Processor) -> "WorkItemRouter":
        """Returns self so registrations can be chained."""
        self._processors[item_type] = processor.process
        return self

    def process(self, item: Any) -> None:
        try:
            handler = self._processors[type(item)]
        except KeyError:
            raise LookupError(f"no processor registered for {type(item).__name__}") from None
        handler(item)
