"""Testing file sources, and the job packs and dispatches every file."""
import random
from statistics import mean

import pytest

from pipeline.bucketing import FirstFitDecreasingStrategy
from pipeline.distributions import ExponentialDistribution
from pipeline.files import (DEFAULT_BUCKET_CAPACITY_BYTES, MB, DirectoryFileSource, FileBucket,
                            FileBucketingJob, FileDescriptor, SimulatedFileSource)
from tests.fakes import (InMemoryFileSource, RecordingDispatcher, SequenceDistribution, StubBucketingStrategy,
                         exponential_files, files_of_sizes_mb)


# ---------- Files and sources ----------
def test_file_descriptor_validates_input():
    with pytest.raises(ValueError):
        FileDescriptor("x", -1)
    with pytest.raises(ValueError):
        FileDescriptor("", 1)


def test_bucket_total_bytes():
    assert FileBucket(tuple(files_of_sizes_mb(1, 2))).total_bytes == 3 * MB


def test_simulated_source_uses_sampled_sizes():
    source = SimulatedFileSource(SequenceDistribution(100.4, 0.2, 5_000), count=100)

    files = source.gather()

    assert len(files) == 100
    assert len({f.path for f in files}) == 100
    assert [f.size_bytes for f in files[:3]] == [100, 1, 5_000]  # rounded, never below 1 byte


def test_simulated_source_sizes_follow_exponential_mean():
    files = SimulatedFileSource(ExponentialDistribution(2 * MB, random.Random(5)), count=20_000).gather()
    assert mean(f.size_bytes for f in files) == pytest.approx(2 * MB, rel=0.03)


def test_directory_source_reports_files_and_sizes(tmp_path):
    (tmp_path / "a.dat").write_bytes(b"x" * 10)
    (tmp_path / "b.dat").write_bytes(b"x" * 20)
    (tmp_path / "skip.txt").write_bytes(b"x")
    (tmp_path / "sub").mkdir()

    files = DirectoryFileSource(str(tmp_path), "*.dat").gather()

    assert sorted(f.size_bytes for f in files) == [10, 20]


def test_exponential_distribution_rejects_invalid_mean():
    for bad in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            ExponentialDistribution(bad)


# ---------- FileBucketingJob ----------
def test_job_dispatches_buckets_covering_all_gathered_files():
    files = exponential_files(100, 2 * MB, seed=11)
    source = InMemoryFileSource(files)
    dispatcher = RecordingDispatcher()

    FileBucketingJob(source, FirstFitDecreasingStrategy(), dispatcher).run()

    assert source.gather_count == 1
    assert sum(len(b.files) for b in dispatcher.items) == 100
    assert sum(b.total_bytes for b in dispatcher.items) == sum(f.size_bytes for f in files)
    assert len(dispatcher.items) < 100, "small files should be packed together"


def test_job_delegates_to_injected_strategy_with_configured_capacity():
    files = files_of_sizes_mb(1, 2, 3)
    predefined = [FileBucket(tuple(files[:1])), FileBucket(tuple(files[1:]))]
    strategy = StubBucketingStrategy(predefined)
    dispatcher = RecordingDispatcher()

    FileBucketingJob(InMemoryFileSource(files), strategy, dispatcher, capacity_bytes=5 * MB).run()

    assert strategy.received_capacity == 5 * MB
    assert strategy.received_files == files
    assert dispatcher.items == predefined


def test_default_bucket_capacity_is_10_mb():
    assert DEFAULT_BUCKET_CAPACITY_BYTES == 10 * 1024 * 1024
