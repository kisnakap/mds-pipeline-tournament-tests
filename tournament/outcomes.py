"""Decides who wins each table: simulated here, or real results via a custom WinnerSelector."""
from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import Mapping, Optional

from .models import Player, Table


class WinnerSelector(ABC):
    @abstractmethod
    def pick_winner(self, table: Table) -> Player: ...


class RandomWinnerSelector(WinnerSelector):
    """Every player at the table is equally likely to win."""

    def __init__(self, rng: Optional[random.Random] = None):
        self._rng = rng or random.Random()

    def pick_winner(self, table: Table) -> Player:
        return self._rng.choice(table.players)


class SkillWeightedWinnerSelector(WinnerSelector):
    """Chance of winning is proportional to a player's skill."""

    def __init__(self, skills: Mapping[Player, float], rng: Optional[random.Random] = None):
        if any(s <= 0 for s in skills.values()):
            raise ValueError("skills must be positive")
        self._skills = dict(skills)
        self._rng = rng or random.Random()

    def pick_winner(self, table: Table) -> Player:
        weights = [self._skills[p] for p in table.players]
        return self._rng.choices(table.players, weights=weights)[0]
