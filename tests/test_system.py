"""End-to-end: both pipelines running in parallel on one shared 10-worker pool."""
import threading
from datetime import datetime, time, timezone

from pipeline.bucketing import FirstFitDecreasingStrategy
from pipeline.files import MB, FileBucket, FileBucketingJob
from pipeline.messaging import MessageBatch, MinibatchService
from pipeline.scheduling import DailyScheduler
from pipeline.workers import WorkerPool, WorkItemRouter
from tests.fakes import (FakeClock, InMemoryFileSource, ManualMessageSource, RecordingProcessor,
                         exponential_files, running, wait_until)


def test_minibatches_and_nightly_buckets_share_one_pool():
    message_clock = FakeClock()
    batches, buckets = RecordingProcessor(), RecordingProcessor()
    router = WorkItemRouter().register(MessageBatch, batches).register(FileBucket, buckets)
    files = exponential_files(100, 2 * MB, seed=21)

    with WorkerPool(router, workers=10) as pool:
        source = ManualMessageSource(message_clock)
        minibatcher = MinibatchService(source, pool, message_clock, window_seconds=300, idle_poll_seconds=0.01)

        nightly_clock = FakeClock(datetime(2026, 1, 1, 12, tzinfo=timezone.utc).timestamp())
        nightly_stop = threading.Event()
        file_job = FileBucketingJob(InMemoryFileSource(files), FirstFitDecreasingStrategy(), pool)

        class RunOnceThenStop:
            def run(self):
                file_job.run()
                nightly_stop.set()

        nightly = DailyScheduler(RunOnceThenStop(), time(2, 0), nightly_clock, timezone.utc)

        with running(minibatcher):
            nightly_thread = threading.Thread(target=nightly.run, args=(nightly_stop,))
            nightly_thread.start()
            for i in range(5):
                source.emit(f"m{i}")
                message_clock.advance(30)
            message_clock.advance(300)
            wait_until(lambda: len(batches.processed) == 1)
            nightly_thread.join(5)

    assert [len(b.messages) for b in batches.processed] == [5]
    assert sum(len(b.files) for b in buckets.processed) == 100
    assert all(b.total_bytes <= 10 * MB or len(b.files) == 1 for b in buckets.processed)
