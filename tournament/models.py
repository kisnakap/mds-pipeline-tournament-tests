"""Immutable value objects describing the tournament."""
from __future__ import annotations

from dataclasses import dataclass

Player = int


@dataclass(frozen=True)
class TournamentConfig:
    """N participants, T tables, G players per table."""

    participants: int
    tables: int
    seats_per_table: int

    def __post_init__(self) -> None:
        if self.seats_per_table < 2:
            raise ValueError("a game needs at least 2 players per table (G >= 2)")
        if self.tables < 1:
            raise ValueError("at least one table is required (T >= 1)")
        if self.participants < self.seats:
            raise ValueError(
                f"every round must fill all {self.tables} tables x {self.seats_per_table} seats, "
                f"so at least {self.seats} participants are needed (got {self.participants})")

    @property
    def seats(self) -> int:
        return self.tables * self.seats_per_table

    @property
    def players(self) -> tuple[Player, ...]:
        return tuple(range(1, self.participants + 1))


@dataclass(frozen=True)
class Table:
    """One table in one round."""
    number: int
    players: tuple[Player, ...]


@dataclass(frozen=True)
class RoundPlan:
    """The seating for a round - seated lists everyone at a table."""
    number: int
    tables: tuple[Table, ...]
    byes: frozenset[Player]     # contenders who sit this round out and keep their title chances
    resting: frozenset[Player]  # eliminated players who sit this round out

    @property
    def seated(self) -> frozenset[Player]:
        return frozenset(p for t in self.tables for p in t.players)


@dataclass(frozen=True)
class RoundResult:
    """What happened in the round - winners[i] won tables[i], and eliminated is before minus after."""
    plan: RoundPlan
    winners: tuple[Player, ...]  # winners[i] won plan.tables[i]
    contenders_before: frozenset[Player]
    contenders_after: frozenset[Player]

    @property
    def eliminated(self) -> frozenset[Player]:
        return self.contenders_before - self.contenders_after


@dataclass(frozen=True)
class TournamentResult:
    """The final answer plus the full history."""
    champion: Player
    rounds: tuple[RoundResult, ...]
