"""Strategies that pack files into buckets of buckets of a given capacity (10 MB by default) (Strategy pattern).
Add one by subclassing BucketingStrategy; it must pass the contract tests in tests/test_bucketing.py."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from .files import FileBucket, FileDescriptor


class BucketingStrategy(ABC):
    """Groups files into buckets.

    Contract: every file ends up in exactly one bucket, and no bucket exceeds
    `capacity_bytes` unless it holds a single file that is larger than the capacity on its own."""

    @abstractmethod
    def pack(self, files: Iterable[FileDescriptor], capacity_bytes: int) -> list[FileBucket]: ...


def _validate(capacity_bytes: int) -> None:
    if capacity_bytes <= 0:
        raise ValueError("capacity_bytes must be positive")


class NextFitStrategy(BucketingStrategy):
    """Fills buckets in arrival order and opens a new one when the next file doesn't fit.
    O(n) time and order-preserving."""

    def pack(self, files: Iterable[FileDescriptor], capacity_bytes: int) -> list[FileBucket]:
        _validate(capacity_bytes)
        buckets: list[FileBucket] = []
        current: list[FileDescriptor] = []
        used = 0
        for f in files:
            if current and used + f.size_bytes > capacity_bytes:
                buckets.append(FileBucket(tuple(current)))
                current, used = [], 0
            current.append(f)
            used += f.size_bytes
        if current:
            buckets.append(FileBucket(tuple(current)))
        return buckets


class FirstFitDecreasingStrategy(BucketingStrategy):
    """Largest file first, each into the first bucket with room. Not optimal."""

    def pack(self, files: Iterable[FileDescriptor], capacity_bytes: int) -> list[FileBucket]:
        _validate(capacity_bytes)
        bins: list[list[FileDescriptor]] = []
        used: list[int] = []
        for f in sorted(files, key=lambda f: f.size_bytes, reverse=True):
            for i, u in enumerate(used):
                if u + f.size_bytes <= capacity_bytes:
                    bins[i].append(f)
                    used[i] += f.size_bytes
                    break
            else:
                bins.append([f])
                used.append(f.size_bytes)
        return [FileBucket(tuple(b)) for b in bins]
