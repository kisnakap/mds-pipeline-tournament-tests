"""Tracks how many times each pair of players has shared a table, and how many
games each player has played. The seating uses it to avoid repeat meetings and 
to rotate fairly who sits out; the report uses it to measure how well players were mixed."""
from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import Iterable

from .models import Player


class MeetingHistory:
    def __init__(self) -> None:
        self._met: dict[Player, Counter] = {}
        self._games: Counter = Counter()

    def record(self, players: Iterable[Player]) -> None:
        group = list(players)
        for p in group:
            self._games[p] += 1
        for a, b in combinations(group, 2):
            self._met.setdefault(a, Counter())[b] += 1
            self._met.setdefault(b, Counter())[a] += 1

    def meetings(self, a: Player, b: Player) -> int:
        """How many times 2 players have played together."""
        return self._met.get(a, Counter())[b]

    def cost_of_joining(self, player: Player, group: Iterable[Player]) -> int:
        """Repeated meetings `player` would add by sitting with `group`."""
        met = self._met.get(player)
        return 0 if met is None else sum(met[o] for o in group)

    def group_cost(self, group: Iterable[Player]) -> int:
        """Gives the total repeats within one table."""
        return sum(self.meetings(a, b) for a, b in combinations(list(group), 2))

    def games_played(self, player: Player) -> int:
        """Used for fair rotation of who sits out."""
        return self._games[player]

    def distinct_opponents(self, player: Player) -> int:
        """How many different people player has played with."""
        return len(self._met.get(player, ()))

    def repeated_meetings(self) -> int:
        """Total number of times any pair met again after their first game together."""
        return sum(n - 1 for met in self._met.values() for n in met.values()) // 2
