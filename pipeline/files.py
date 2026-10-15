"""Files, file sources, and the nightly job that packs files into buckets."""
from __future__ import annotations

import fnmatch
import logging
import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .core import Dispatcher, Job
from .distributions import Distribution

if TYPE_CHECKING:
    from .bucketing import BucketingStrategy

log = logging.getLogger(__name__)

MB = 1024 * 1024
DEFAULT_BUCKET_CAPACITY_BYTES = 10 * MB


@dataclass(frozen=True)
class FileDescriptor:
    path: str
    size_bytes: int

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("path must not be empty")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must not be negative")


@dataclass(frozen=True)
class FileBucket:
    """A group of files processed together by one worker."""

    files: tuple[FileDescriptor, ...]
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def total_bytes(self) -> int:
        return sum(f.size_bytes for f in self.files)


class FileSource(ABC):
    @abstractmethod
    def gather(self) -> list[FileDescriptor]:
        """Where files come from."""


class SimulatedFileSource(FileSource):
    """Produces `count` synthetic files with sizes drawn from a distribution (e.g. exponential). 
    Rounded and never below 1 byte."""

    def __init__(self, size_bytes: Distribution, count: int = 100):
        if count < 0:
            raise ValueError("count must not be negative")
        self._sizes = size_bytes
        self._count = count

    def gather(self) -> list[FileDescriptor]:
        return [FileDescriptor(f"file-{i:03d}.dat", max(1, round(self._sizes.sample())))
                for i in range(1, self._count + 1)]


class DirectoryFileSource(FileSource):
    """Gathers the files currently present in a directory."""

    def __init__(self, directory: str, pattern: str = "*"):
        self._directory = directory
        self._pattern = pattern

    def gather(self) -> list[FileDescriptor]:
        with os.scandir(self._directory) as entries:
            return [FileDescriptor(e.path, e.stat().st_size) for e in entries
                    if e.is_file() and fnmatch.fnmatch(e.name, self._pattern)]


class FileBucketingJob(Job):
    """Gathers the files, packs them with the injected BucketingStrategy
    and dispatches each bucket to the worker pool."""

    def __init__(self, source: FileSource, strategy: "BucketingStrategy", dispatcher: Dispatcher,
                 capacity_bytes: int = DEFAULT_BUCKET_CAPACITY_BYTES):
        self._source = source
        self._strategy = strategy
        self._dispatcher = dispatcher
        self._capacity = capacity_bytes

    def run(self) -> list[FileBucket]:
        files = self._source.gather()
        buckets = self._strategy.pack(files, self._capacity)
        log.debug("packed %d files into %d buckets using %s",
                 len(files), len(buckets), type(self._strategy).__name__)
        for bucket in buckets:
            self._dispatcher.dispatch(bucket)
        return buckets
