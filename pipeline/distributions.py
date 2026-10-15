"""Probability distributions for the simulated sources: exponential gaps between messages
(a Poisson process) and exponential file sizes."""
from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from typing import Optional


class Distribution(ABC):
    @abstractmethod
    def sample(self) -> float: ...


class ExponentialDistribution(Distribution):
    """ExponentialDistribution serves two purposes:
    - gaps between messages: exponential gaps produce a Poisson process (mean 6 s at 10 msgs/min);
    - file sizes: the nightly files have exponentially distributed sizes.

    A seeded random.Random can be injected so simulations and tests are reproducible."""

    def __init__(self, mean: float, rng: Optional[random.Random] = None):
        if not (mean > 0 and math.isfinite(mean)):
            raise ValueError(f"mean must be a positive finite number, got {mean!r}")
        self.mean = mean
        self._rng = rng or random.Random()

    @classmethod
    def from_rate(cls, rate: float, rng: Optional[random.Random] = None) -> "ExponentialDistribution":
        """Convenience constructor where `rate` = events per unit of time (lambda); the mean is 1 / rate."""
        if not rate > 0:
            raise ValueError(f"rate must be positive, got {rate!r}")
        return cls(1.0 / rate, rng)

    def sample(self) -> float:
        return self._rng.expovariate(1.0 / self.mean)
