"""Test doubles for the game-night tournament."""
from __future__ import annotations

import random
from typing import Callable

from tournament.arrangement import ArrangementStrategy, GreedyMixingArrangement, RandomArrangement
from tournament.elimination import ContenderMustBeatContenderRule
from tournament.models import Player, RoundResult, Table, TournamentConfig
from tournament.outcomes import RandomWinnerSelector, WinnerSelector
from tournament.planner import SeatingPlanner
from tournament.tournament import RoundObserver, Tournament


class LowestIdWins(WinnerSelector):
    """Deterministic: the player with the smallest number always wins."""

    def pick_winner(self, table: Table) -> Player:
        return min(table.players)


class NonContenderWins(WinnerSelector):
    """Adversarial: an eliminated player wins whenever one is at the table."""

    def __init__(self, contenders: Callable[[], frozenset[Player]]):
        self._contenders = contenders

    def pick_winner(self, table: Table) -> Player:
        others = [p for p in table.players if p not in self._contenders()]
        return min(others) if others else min(table.players)


class OutsideWinner(WinnerSelector):
    """Broken selector returning someone who did not play."""

    def pick_winner(self, table: Table) -> Player:
        return -1


class RecordingObserver(RoundObserver):
    def __init__(self) -> None:
        self.results: list[RoundResult] = []

    def on_round(self, result: RoundResult) -> None:
        self.results.append(result)


def make_tournament(config: TournamentConfig, seed: int = 0, selector: WinnerSelector | None = None,
                    arrangement: str = "greedy", observers=()) -> Tournament:
    rng = random.Random(seed)
    strategy: ArrangementStrategy = GreedyMixingArrangement(rng) if arrangement == "greedy" else RandomArrangement(rng)
    return Tournament(config, SeatingPlanner(config, strategy, rng), selector or RandomWinnerSelector(rng),
                      ContenderMustBeatContenderRule(), observers=observers)
