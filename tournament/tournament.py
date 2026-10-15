"""Runs the tournament round by round until a single overall winner remains,
notifying observers after each round."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Optional

from .elimination import EliminationRule
from .history import MeetingHistory
from .models import Player, RoundResult, TournamentConfig, TournamentResult
from .outcomes import WinnerSelector
from .planner import SeatingPlanner


class TournamentNotFinishedError(RuntimeError):
    pass


class RoundObserver(ABC):
    """Hook for printing, saving or a UI without changing Tournament (Open/Closed principle)."""

    @abstractmethod
    def on_round(self, result: RoundResult) -> None: ...


class Tournament:
    """Everything is injected: config, planner, winner selector, elimination rule, history and observers."""
    def __init__(self, config: TournamentConfig, planner: SeatingPlanner, winner_selector: WinnerSelector,
                 elimination_rule: EliminationRule, history: Optional[MeetingHistory] = None,
                 observers: Iterable[RoundObserver] = ()):
        self._config = config
        self._planner = planner
        self._winner_selector = winner_selector
        self._rule = elimination_rule
        self._history = history or MeetingHistory()
        self._observers = list(observers)
        self._contenders = frozenset(config.players)
        self._rounds: list[RoundResult] = []

    @property
    def contenders(self) -> frozenset[Player]:
        return self._contenders

    @property
    def history(self) -> MeetingHistory:
        return self._history

    @property
    def is_finished(self) -> bool:
        return len(self._contenders) == 1

    def play_round(self) -> RoundResult:
        """1. Refuses to play if a champion already exists.
           2. Asks the planner for the seating.
           3. Asks the winner selector for each table's winner, and checks that each winner actually sat at that
              table. This guards against a buggy or manually entered result.
           4. Records every table in the history.
           5. Applies the elimination rule, and fails loudly if a custom rule ever removes every contender.
           6. Stores the RoundResult and notifies the observers."""
        
        if self.is_finished:
            raise RuntimeError("the tournament already has a champion")

        plan = self._planner.plan(len(self._rounds) + 1, self._contenders, self._history)
        winners = tuple(self._winner_selector.pick_winner(t) for t in plan.tables)
        for table, winner in zip(plan.tables, winners):
            if winner not in table.players:
                raise ValueError(f"winner {winner} did not play at table {table.number}")
            self._history.record(table.players)

        after = self._rule.contenders_after(self._contenders, plan.tables, winners)
        if not after:
            raise RuntimeError("elimination rule removed every contender")

        result = RoundResult(plan, winners, self._contenders, after)
        self._contenders = after
        self._rounds.append(result)
        for observer in self._observers:
            observer.on_round(result)
        return result

    def run(self, max_rounds: int = 1_000) -> TournamentResult:
        while not self.is_finished:
            if len(self._rounds) >= max_rounds:
                raise TournamentNotFinishedError(
                    # TournamentNotFinishedError: raised if no champion is found within max_rounds,
                    # instead of naming an arbitrary winner.
                    f"no champion after {max_rounds} rounds ({len(self._contenders)} contenders left)")
            self.play_round()
        (champion,) = self._contenders
        return TournamentResult(champion, tuple(self._rounds))
