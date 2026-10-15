"""Who keeps their chance at the overall title after a round."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from .models import Player, Table


class EliminationRule(ABC):
    @abstractmethod
    def contenders_after(self, contenders: frozenset[Player], tables: Sequence[Table],
                         winners: Sequence[Player]) -> frozenset[Player]: ...


class ContenderMustBeatContenderRule(EliminationRule):
    """A contender loses their title chance only when another contender wins at their table.

    - Table of contenders only: the winner stays in, the other G-1 are out.
    - Mixed table: if a contender wins, the other contenders there are out; if an already
      eliminated player wins, no contender at that table loses anything (they meet again later).

    The contender set shrinks monotonically and can never become empty. A champion is always found."""

    def contenders_after(self, contenders: frozenset[Player], tables: Sequence[Table],
                         winners: Sequence[Player]) -> frozenset[Player]:
        remaining = set(contenders)
        for table, winner in zip(tables, winners):
            if winner in contenders:
                remaining.difference_update(p for p in table.players if p in contenders and p != winner)
        return frozenset(remaining)
