"""Testing 5-minute windows from the first message, boundary handling, 
batches don't wait for processing, Poisson statistics."""
import itertools
import random
import threading
import time
from statistics import mean, pvariance

import pytest

from pipeline.core import SystemClock
from pipeline.distributions import ExponentialDistribution
from pipeline.messaging import Message, MinibatchService, PoissonMessageSource, TimeWindowAccumulator
from pipeline.workers import WorkerPool
from tests.fakes import (FailingMessageSource, FakeClock, GatedProcessor, ManualMessageSource,
                         RecordingDispatcher, SequenceDistribution, running, wait_until)

WINDOW = 300.0


def msg(payload, t):
    return Message(payload, t)


def payloads(batch):
    return [m.payload for m in batch.messages]


# ---------- TimeWindowAccumulator: pure, deterministic ----------
class TestTimeWindowAccumulator:
    def test_messages_within_window_form_one_batch(self):
        acc = TimeWindowAccumulator(WINDOW)
        for p, t in [("a", 0), ("b", 120), ("c", 299)]:
            assert acc.add(msg(p, t)) is None
        assert acc.poll(299.9) is None

        batch = acc.poll(300)

        assert payloads(batch) == ["a", "b", "c"]
        assert (batch.window_start, batch.window_end) == (0, 300)

    def test_window_starts_at_first_message_not_at_fixed_boundaries(self):
        acc = TimeWindowAccumulator(WINDOW)
        acc.add(msg("a", 42))
        assert acc.poll(341) is None
        assert acc.poll(342).window_start == 42

    def test_message_at_window_end_starts_next_batch(self):
        acc = TimeWindowAccumulator(WINDOW)
        acc.add(msg("a", 0))

        closed = acc.add(msg("b", 300))

        assert payloads(closed) == ["a"]
        assert payloads(acc.poll(600)) == ["b"]

    def test_first_message_after_gap_opens_new_window(self):
        acc = TimeWindowAccumulator(WINDOW)
        acc.add(msg("a", 0))
        acc.poll(300)
        acc.add(msg("b", 360))
        assert acc.poll(659) is None
        assert acc.poll(660).window_start == 360

    def test_empty_accumulator_produces_nothing(self):
        acc = TimeWindowAccumulator(WINDOW)
        assert acc.poll(10_000) is None
        assert acc.flush() is None
        assert acc.seconds_until_close(0) is None

    def test_flush_returns_partial_batch(self):
        acc = TimeWindowAccumulator(WINDOW)
        acc.add(msg("a", 0))
        assert payloads(acc.flush()) == ["a"]
        assert acc.flush() is None

    @pytest.mark.parametrize("window", [0, -1])
    def test_rejects_non_positive_window(self, window):
        with pytest.raises(ValueError):
            TimeWindowAccumulator(window)


# ---------- MinibatchService: threads + mocks + fake clock ----------
class TestMinibatchService:
    def setup_method(self):
        self.clock = FakeClock()
        self.source = ManualMessageSource(self.clock)
        self.dispatcher = RecordingDispatcher()

    def service(self, dispatcher=None):
        return MinibatchService(self.source, dispatcher or self.dispatcher, self.clock,
                                window_seconds=WINDOW, idle_poll_seconds=0.01)

    def test_messages_within_window_are_dispatched_as_one_batch(self):
        with running(self.service()):
            self.source.emit("a")
            self.clock.advance(120)
            self.source.emit("b")
            self.clock.advance(179)
            self.source.emit("c")
            time.sleep(0.05)
            assert self.dispatcher.items == []

            self.clock.advance(1)

            [batch] = self.dispatcher.wait_for(1)
            assert payloads(batch) == ["a", "b", "c"]

    def test_batch_is_dispatched_on_deadline_without_further_messages(self):
        with running(self.service()):
            self.source.emit("a")
            self.clock.advance(WINDOW)
            [batch] = self.dispatcher.wait_for(1)
            assert payloads(batch) == ["a"]

    def test_first_message_after_window_opens_new_batch(self):
        with running(self.service()):
            self.source.emit("a")
            self.clock.advance(WINDOW)
            self.dispatcher.wait_for(1)

            self.clock.advance(60)
            self.source.emit("b")
            self.clock.advance(WINDOW)

            batches = self.dispatcher.wait_for(2)
            assert payloads(batches[1]) == ["b"]
            assert batches[1].window_start == 360

    def test_message_stamped_at_window_end_belongs_to_next_batch(self):
        with running(self.service()):
            self.source.emit("a")
            self.clock.advance(WINDOW)
            self.source.emit("b")
            self.clock.advance(WINDOW)

            batches = self.dispatcher.wait_for(2)
            assert [payloads(b) for b in batches] == [["a"], ["b"]]

    def test_source_completion_flushes_open_batch_and_returns(self):
        self.source.emit("a", wait=False)
        self.source.emit("b", wait=False)
        self.source.complete()

        self.service().run(threading.Event())

        assert [payloads(b) for b in self.dispatcher.items] == [["a", "b"]]

    def test_stop_flushes_open_batch(self):
        with running(self.service()):
            self.source.emit("a")
        assert [payloads(b) for b in self.dispatcher.items] == [["a"]]

    def test_source_failure_is_raised_from_run(self):
        service = MinibatchService(FailingMessageSource(), self.dispatcher, self.clock, idle_poll_seconds=0.01)
        with pytest.raises(RuntimeError, match="message source failed"):
            service.run(threading.Event())

    def test_new_batch_is_formed_while_previous_batch_is_still_processing(self):
        processor = GatedProcessor()
        pool = WorkerPool(processor, workers=10)
        try:
            with running(self.service(pool)):
                self.source.emit("a")
                self.clock.advance(WINDOW)
                wait_until(lambda: processor.started == 1)

                self.clock.advance(60)
                self.source.emit("b")
                self.clock.advance(WINDOW)
                wait_until(lambda: processor.started == 2)

                assert processor.in_flight == 2  # batch 1 still blocked, batch 2 already running
        finally:
            processor.release()
            pool.shutdown()


# ---------- PoissonMessageSource ----------
class TestPoissonMessageSource:
    def test_messages_are_separated_by_sampled_gaps(self):
        clock = FakeClock()
        source = PoissonMessageSource(SequenceDistribution(6, 10, 2), clock)

        stamps = [m.timestamp for m in itertools.islice(source.messages(threading.Event()), 3)]

        assert stamps == [6, 16, 18]

    def test_ten_per_minute_gives_six_second_mean_gap(self):
        clock = FakeClock()
        source = PoissonMessageSource.with_rate_per_minute(10, clock, rng=random.Random(42))

        stamps = [m.timestamp for m in itertools.islice(source.messages(threading.Event()), 20_000)]
        gaps = [b - a for a, b in zip([0.0] + stamps, stamps)]

        assert mean(gaps) == pytest.approx(6.0, rel=0.03)

    def test_counts_per_five_minute_window_are_poisson(self):
        # Poisson(lambda * t): mean == variance == 10/min * 5 min == 50.
        gaps = ExponentialDistribution.from_rate(10 / 60.0, random.Random(7))
        counts = []
        for _ in range(5_000):
            n, t = 0, gaps.sample()
            while t < WINDOW:
                n, t = n + 1, t + gaps.sample()
            counts.append(n)

        assert 49 <= mean(counts) <= 51
        assert 45 <= pvariance(counts) <= 55

    def test_stops_promptly_when_stop_is_set(self):
        stop = threading.Event()
        stop.set()
        source = PoissonMessageSource.with_rate_per_minute(10, SystemClock())
        assert list(source.messages(stop)) == []

    def test_rejects_non_positive_rate(self):
        with pytest.raises(ValueError):
            PoissonMessageSource.with_rate_per_minute(0, FakeClock())
