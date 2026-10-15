"""Composition root for data processing pipeline.

    python main.py                          # 5-minute windows, files nightly at 02:00; Ctrl+C to stop
    python main.py --window 10 --files-now  # demo (10 s windows); Ctrl+C to stop
"""
from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from datetime import time as clock_time

from pipeline.bucketing import FirstFitDecreasingStrategy, NextFitStrategy
from pipeline.core import Processor, SystemClock
from pipeline.distributions import ExponentialDistribution
from pipeline.files import MB, FileBucket, FileBucketingJob, SimulatedFileSource
from pipeline.messaging import MessageBatch, MinibatchService, PoissonMessageSource
from pipeline.scheduling import DailyScheduler
from pipeline.workers import WorkerPool, WorkItemRouter

log = logging.getLogger("main")

STRATEGIES = {"ffd": FirstFitDecreasingStrategy, "next-fit": NextFitStrategy}


class LoggingBatchProcessor(Processor):
    """Placeholder for real minibatch processing."""

    def process(self, batch: MessageBatch) -> None:
        log.info("processing minibatch %s: %d messages", batch.id[:8], len(batch.messages))
        time.sleep(0.1 * len(batch.messages))


class LoggingBucketProcessor(Processor):
    """Placeholder for real file-bucket processing."""

    def process(self, bucket: FileBucket) -> None:
        log.info("processing bucket %s: %d files, %.2f MB", bucket.id[:8], len(bucket.files), bucket.total_bytes / MB)
        time.sleep(bucket.total_bytes / (100 * MB))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rate", type=float, default=10.0, help="messages per minute")
    parser.add_argument("--window", type=float, default=300.0, help="minibatch window in seconds")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--run-at", default="02:00", help="nightly file job time, HH:MM local")
    parser.add_argument("--files", type=int, default=100)
    parser.add_argument("--mean-file-mb", type=float, default=2.0)
    parser.add_argument("--strategy", choices=STRATEGIES, default="ffd")
    parser.add_argument("--files-now", action="store_true", help="also run the file job once at startup")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(threadName)-14s %(name)s: %(message)s")
    clock = SystemClock()
    stop = threading.Event()
    # `docker stop` sends SIGTERM; treat it like Ctrl+C so open batches are flushed.
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    router = (WorkItemRouter()
              .register(MessageBatch, LoggingBatchProcessor())
              .register(FileBucket, LoggingBucketProcessor()))
    pool = WorkerPool(router, workers=args.workers)  # one pool shared by both pipelines

    minibatcher = MinibatchService(
        PoissonMessageSource.with_rate_per_minute(args.rate, clock), pool, clock, window_seconds=args.window)

    file_job = FileBucketingJob(
        SimulatedFileSource(ExponentialDistribution(args.mean_file_mb * MB), count=args.files),
        STRATEGIES[args.strategy](),
        pool)
    hour, minute = map(int, args.run_at.split(":"))
    nightly = DailyScheduler(file_job, clock_time(hour, minute), clock)

    threads = [threading.Thread(target=p.run, args=(stop,), name=name)
               for name, p in [("minibatcher", minibatcher), ("nightly-files", nightly)]]
    for t in threads:
        t.start()
    if args.files_now:
        file_job.run()

    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
    except KeyboardInterrupt:
        log.info("stopping...")
        stop.set()
    finally:
        for t in threads:
            t.join()
        pool.shutdown(wait=True)


if __name__ == "__main__":
    main()
