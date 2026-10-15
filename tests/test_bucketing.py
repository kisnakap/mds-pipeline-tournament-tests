"""Contract tests every BucketingStrategy must pass, plus strategy-specific examples.
Every strategy keeps the 10 MB rule and packs each file once. 
To add a strategy, add its class to STRATEGIES."""
import math

import pytest

from pipeline.bucketing import FirstFitDecreasingStrategy, NextFitStrategy
from pipeline.files import MB, FileDescriptor
from tests.fakes import exponential_files, files_of_sizes_mb

CAPACITY = 10 * MB
STRATEGIES = [NextFitStrategy, FirstFitDecreasingStrategy]


def sizes_mb(bucket):
    return [f.size_bytes / MB for f in bucket.files]


@pytest.fixture(params=STRATEGIES, ids=lambda cls: cls.__name__)
def strategy(request):
    return request.param()


def test_every_file_is_packed_exactly_once(strategy):
    files = exponential_files(100, 2 * MB, seed=1)

    buckets = strategy.pack(files, CAPACITY)

    packed = sorted(f.path for b in buckets for f in b.files)
    assert packed == sorted(f.path for f in files)


def test_no_bucket_exceeds_capacity_unless_it_holds_one_oversized_file(strategy):
    files = exponential_files(100, 2 * MB, seed=2) + [FileDescriptor("huge.dat", 25 * MB)]

    buckets = strategy.pack(files, CAPACITY)

    assert all(b.total_bytes <= CAPACITY or len(b.files) == 1 for b in buckets)
    assert any([f.path for f in b.files] == ["huge.dat"] for b in buckets)


def test_bucket_count_is_at_least_the_theoretical_minimum(strategy):
    files = exponential_files(100, 2 * MB, seed=3)
    # Each oversized file needs a bucket of its own; the rest need at least total / capacity.
    oversized = [f for f in files if f.size_bytes > CAPACITY]
    rest = sum(f.size_bytes for f in files if f.size_bytes <= CAPACITY)
    lower_bound = len(oversized) + math.ceil(rest / CAPACITY)

    buckets = strategy.pack(files, CAPACITY)

    assert lower_bound <= len(buckets) < len(files)


def test_file_exactly_at_capacity_fits(strategy):
    buckets = strategy.pack(files_of_sizes_mb(10, 10), CAPACITY)
    assert [sizes_mb(b) for b in buckets] == [[10], [10]]


def test_empty_input_produces_no_buckets(strategy):
    assert strategy.pack([], CAPACITY) == []


@pytest.mark.parametrize("capacity", [0, -1])
def test_non_positive_capacity_is_rejected(strategy, capacity):
    with pytest.raises(ValueError):
        strategy.pack(files_of_sizes_mb(1), capacity)


def test_next_fit_packs_in_arrival_order():
    buckets = NextFitStrategy().pack(files_of_sizes_mb(6, 5, 4, 3, 2), CAPACITY)
    assert [sizes_mb(b) for b in buckets] == [[6], [5, 4], [3, 2]]


def test_first_fit_decreasing_puts_largest_first_into_first_bucket_with_room():
    buckets = FirstFitDecreasingStrategy().pack(files_of_sizes_mb(2, 5, 3, 6, 4), CAPACITY)
    assert [sizes_mb(b) for b in buckets] == [[6, 4], [5, 3, 2]]
