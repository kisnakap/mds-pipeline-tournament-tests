"""Measures how well players were mixed: distinct opponents and repeated meetings.
Used to compare seating strategies."""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Sequence

from .history import MeetingHistory
from .models import Player


@dataclass(frozen=True)
class MixingReport:
    rounds: int
    average_distinct_opponents: float  # average distinct opponents among non-winners
    fewest_distinct_opponents: int  # fewest distinct opponents among non-winners
    repeated_meetings: int
    max_possible_opponents: int        # maximum possible distinct opponents (N − 1), for scale


def mixing_report(history: MeetingHistory, players: Sequence[Player], champion: Player, rounds: int) -> MixingReport:
    others = [history.distinct_opponents(p) for p in players if p != champion]
    return MixingReport(
        rounds=rounds,
        average_distinct_opponents=mean(others),
        fewest_distinct_opponents=min(others),
        repeated_meetings=history.repeated_meetings(),
        max_possible_opponents=len(players) - 1)
