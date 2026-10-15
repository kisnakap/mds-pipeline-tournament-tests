"""Builds the seating for one round: who plays, who sits out, and who shares a table.

  The planner applies the tournament rules (contenders packed G per table, byes, fair rotation);
  the arrangement strategy then decides the exact groups to minimise repeat meetings."""
from __future__ import annotations

import random
from typing import Iterable, Optional

from .arrangement import ArrangementStrategy
from .history import MeetingHistory
from .models import Player, RoundPlan, Table, TournamentConfig


class SeatingPlanner:
    """Builds one round's seating.

    1. Contenders are packed G per table, so each such table removes G-1 contenders.
    2. Leftover contenders (fewer than G) share one mixed table, so they can still knock each other out.
    3. If there are more contenders than seats, the rest get a bye and keep their title chances.
    4. Every remaining seat is filled with eliminated players, those who played least first, 
       so all T tables are used every round.
    5. The arrangement strategy splits players into tables."""

    def __init__(self, config: TournamentConfig, arrangement: ArrangementStrategy,
                 rng: Optional[random.Random] = None):
        self._config = config
        self._arrangement = arrangement
        self._rng = rng or random.Random()

    def plan(self, number: int, contenders: frozenset[Player], history: MeetingHistory) -> RoundPlan:
        size, tables, seats = self._config.seats_per_table, self._config.tables, self._config.seats

        ordered_contenders = self._fewest_games_first(contenders, history)
        full_tables = min(len(contenders) // size, tables)
        at_full_tables = ordered_contenders[:full_tables * size]
        leftover = ordered_contenders[full_tables * size:]
        if full_tables < tables:
            mixed, byes = leftover, []  # fewer than G left, they share one table
        else:
            mixed, byes = [], leftover  # every table already holds contenders only

        others = self._fewest_games_first((p for p in self._config.players if p not in contenders), history)
        free_seats = seats - len(at_full_tables) - len(mixed)
        fillers, resting = others[:free_seats], others[free_seats:]

        groups = []
        if at_full_tables:
            groups += self._arrangement.arrange([], at_full_tables, size, history)
        if mixed or fillers:
            groups += self._arrangement.arrange([mixed] if mixed else [], fillers, size, history)

        return RoundPlan(
            number=number,
            tables=tuple(Table(i, tuple(g)) for i, g in enumerate(groups, start=1)),
            byes=frozenset(byes),
            resting=frozenset(resting))

    def _fewest_games_first(self, players: Iterable[Player], history: MeetingHistory) -> list[Player]:
        keyed = [(history.games_played(p), self._rng.random(), p) for p in players]
        return [p for *_, p in sorted(keyed)]
