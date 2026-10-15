"""Testing at most 10 at once, non-blocking dispatch, failures isolated."""
import time
from dataclasses import dataclass

import pytest

from pipeline.files import FileBucket
from pipeline.messaging import MessageBatch
from pipeline.workers import WorkerPool, WorkItemRouter
from tests.fakes import GatedProcessor, RecordingProcessor, wait_until


def test_every_dispatched_item_is_processed():
    processor = RecordingProcessor()
    with WorkerPool(processor) as pool:
        for i in range(100):
            pool.dispatch(i)
    assert sorted(processor.processed) == list(range(100))


def test_at_most_worker_count_items_run_concurrently():
    processor = GatedProcessor()
    pool = WorkerPool(processor, workers=10)
    try:
        for i in range(25):
            pool.dispatch(i)
        wait_until(lambda: processor.started == 10)
        time.sleep(0.1)
        assert processor.started == 10
    finally:
        processor.release()
        pool.shutdown()
    assert processor.completed == 25
    assert processor.max_in_flight == 10


def test_dispatch_does_not_wait_for_processing():
    processor = GatedProcessor()
    pool = WorkerPool(processor, workers=1)
    try:
        started = time.monotonic()
        pool.dispatch(1)
        pool.dispatch(2)
        assert time.monotonic() - started < 0.5
    finally:
        processor.release()
        pool.shutdown()


def test_failing_item_does_not_stop_the_pool():
    processed = []

    class Flaky(RecordingProcessor):
        def process(self, item):
            if item == 3:
                raise RuntimeError("boom")
            processed.append(item)

    with WorkerPool(Flaky(), workers=1) as pool:
        for i in range(1, 6):
            pool.dispatch(i)
    assert processed == [1, 2, 4, 5]


def test_dispatch_after_shutdown_is_rejected():
    pool = WorkerPool(RecordingProcessor())
    pool.shutdown()
    with pytest.raises(RuntimeError):
        pool.dispatch(1)


@pytest.mark.parametrize("workers", [0, -1])
def test_rejects_non_positive_worker_count(workers):
    with pytest.raises(ValueError):
        WorkerPool(RecordingProcessor(), workers=workers)


def test_router_sends_each_item_to_processor_for_its_type():
    batches, buckets = RecordingProcessor(), RecordingProcessor()
    router = WorkItemRouter().register(MessageBatch, batches).register(FileBucket, buckets)
    batch, bucket = MessageBatch((), 0, 300), FileBucket(())

    router.process(batch)
    router.process(bucket)

    assert batches.processed == [batch]
    assert buckets.processed == [bucket]


def test_router_rejects_unregistered_type():
    @dataclass
    class Unknown:
        pass

    with pytest.raises(LookupError):
        WorkItemRouter().process(Unknown())
