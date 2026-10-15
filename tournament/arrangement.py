"""Strategies that decide who sits with whom (Strategy pattern).

  Maximising the number of different people everyone plays with is the Social Golfer Problem,
  which is NP-hard, so the greedy strategy is a good heuristic, not a guaranteed optimum."""
from __future__ import annotations

import random
from abc import ABC, abstractmethod
from itertools import combinations
from typing import Optional, Sequence

from .history import MeetingHistory
from .models import Player


class ArrangementStrategy(ABC):
    @abstractmethod
    def arrange(self, seeds: Sequence[Sequence[Player]], free: Sequence[Player], group_size: int,
                history: MeetingHistory) -> list[list[Player]]:
        """Completes every seed group with free players, then groups the remaining free players.

        Seed players always stay together in their group - like leftover contenders who need to share a
        table. All free players are used exactly once."""


def _validate(seeds: Sequence[Sequence[Player]], free: Sequence[Player], group_size: int) -> None:
    if any(len(s) > group_size for s in seeds):
        raise ValueError("a seed group is larger than the table")
    if (sum(len(s) for s in seeds) + len(free)) % group_size:
        raise ValueError("players cannot be split into full tables")
    if sum(group_size - len(s) for s in seeds) > len(free):
        raise ValueError("not enough free players to complete the seed groups")


class RandomArrangement(ArrangementStrategy):
    """Baseline: random seating, ignores history. Used as a baseline for comparison."""

    def __init__(self, rng: Optional[random.Random] = None):
        self._rng = rng or random.Random()

    def arrange(self, seeds, free, group_size, history):
        _validate(seeds, free, group_size)
        pool = list(free)
        self._rng.shuffle(pool)
        groups = [list(s) for s in seeds]
        for group in groups:
            while len(group) < group_size:
                group.append(pool.pop())
        groups += [pool[i:i + group_size] for i in range(0, len(pool), group_size)]
        return groups


class GreedyMixingArrangement(ArrangementStrategy):
    """Minimises repeated meetings: greedy build followed by pairwise-swap local search.

    1. Each table is filled one seat at a time with the free player who has met the people
       already at that table the fewest times.
    2. Then any two non-seed players at different tables are swapped whenever that lowers
       the total number of repeated meetings, until no swap helps, up to max_passes."""

    def __init__(self, rng: Optional[random.Random] = None, max_passes: int = 50):
        self._rng = rng or random.Random()
        self._max_passes = max_passes

    def arrange(self, seeds, free, group_size, history):
        _validate(seeds, free, group_size)
        pool = list(free)
        self._rng.shuffle(pool)
        groups = [list(s) for s in seeds]
        fixed = [len(s) for s in seeds]  # seed players sit first in each group and never move
        new_groups = (len(pool) - sum(group_size - len(s) for s in seeds)) // group_size
        groups += [[] for _ in range(new_groups)]
        fixed += [0] * new_groups

        for group in groups:
            while len(group) < group_size:
                best = min(pool, key=lambda p: history.cost_of_joining(p, group))
                pool.remove(best)
                group.append(best)

        self._improve(groups, fixed, history)
        return groups

    def _improve(self, groups: list[list[Player]], fixed: list[int], history: MeetingHistory) -> None:
        for _ in range(self._max_passes):
            improved = False
            for i, j in combinations(range(len(groups)), 2):
                gi, gj = groups[i], groups[j]
                for ai in range(fixed[i], len(gi)):
                    for bj in range(fixed[j], len(gj)):
                        a, b = gi[ai], gj[bj]
                        rest_i = gi[:ai] + gi[ai + 1:]
                        rest_j = gj[:bj] + gj[bj + 1:]
                        delta = (history.cost_of_joining(b, rest_i) + history.cost_of_joining(a, rest_j)
                                 - history.cost_of_joining(a, rest_i) - history.cost_of_joining(b, rest_j))
                        if delta < 0:
                            gi[ai], gj[bj] = b, a
                            improved = True
            if not improved:
                return
