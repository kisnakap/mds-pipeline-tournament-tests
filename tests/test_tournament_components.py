"""Testing aach tournament class on its own: rules, seating, planner."""
import random
from collections import Counter
from itertools import combinations

import pytest

from tournament.arrangement import GreedyMixingArrangement, RandomArrangement
from tournament.elimination import ContenderMustBeatContenderRule
from tournament.history import MeetingHistory
from tournament.models import Table, TournamentConfig
from tournament.outcomes import SkillWeightedWinnerSelector
from tournament.planner import SeatingPlanner
from tournament.report import mixing_report


# ---------- TournamentConfig ----------
@pytest.mark.parametrize("n, t, g", [(10, 2, 1), (10, 0, 4), (7, 2, 4)])
def test_config_rejects_impossible_setups(n, t, g):
    with pytest.raises(ValueError):
        TournamentConfig(n, t, g)


def test_config_derived_values():
    config = TournamentConfig(10, 2, 4)
    assert config.seats == 8
    assert config.players == tuple(range(1, 11))


# ---------- MeetingHistory ----------
def test_history_counts_meetings_games_and_opponents():
    h = MeetingHistory()
    h.record([1, 2, 3])
    h.record([1, 2, 4])

    assert h.meetings(1, 2) == 2 and h.meetings(2, 1) == 2
    assert h.meetings(3, 4) == 0
    assert h.games_played(1) == 2 and h.games_played(9) == 0
    assert h.distinct_opponents(1) == 3
    assert h.cost_of_joining(1, [2, 3]) == 3
    assert h.group_cost([1, 2, 3]) == 2 + 1 + 1
    assert h.repeated_meetings() == 1


# ---------- Elimination rule ----------
RULE = ContenderMustBeatContenderRule()


def test_all_contender_table_keeps_only_winner():
    after = RULE.contenders_after(frozenset({1, 2, 3, 4}), [Table(1, (1, 2, 3, 4))], [3])
    assert after == {3}


def test_mixed_table_contender_win_knocks_out_other_contenders_only():
    after = RULE.contenders_after(frozenset({1, 2, 9}), [Table(1, (1, 2, 5, 6))], [1])
    assert after == {1, 9}  # 9 had a bye


def test_mixed_table_won_by_eliminated_player_changes_nothing():
    contenders = frozenset({1, 2})
    assert RULE.contenders_after(contenders, [Table(1, (1, 2, 5, 6))], [5]) == contenders


# ---------- Winner selection ----------
def test_skill_weighted_selector_favours_skilled_player():
    selector = SkillWeightedWinnerSelector({1: 99, 2: 1}, random.Random(3))
    wins = Counter(selector.pick_winner(Table(1, (1, 2))) for _ in range(2_000))
    assert wins[1] > 1_900


def test_skill_weighted_selector_rejects_non_positive_skill():
    with pytest.raises(ValueError):
        SkillWeightedWinnerSelector({1: 0})


# ---------- Arrangement strategies (contract tests for every strategy) ----------
@pytest.fixture(params=[GreedyMixingArrangement, RandomArrangement], ids=lambda c: c.__name__)
def strategy(request):
    return request.param(random.Random(1))


def test_arrangement_keeps_seeds_together_and_uses_every_free_player_once(strategy):
    groups = strategy.arrange([[1, 2], [3]], list(range(4, 17)), 4, MeetingHistory())

    assert len(groups) == 4 and all(len(g) == 4 for g in groups)
    assert {1, 2} <= set(groups[0]) and 3 in groups[1]
    assert Counter(p for g in groups for p in g) == Counter(range(1, 17))


@pytest.mark.parametrize("seeds, free", [([[1, 2, 3, 4, 5]], [6, 7, 8]), ([], [1, 2, 3]), ([[1, 2, 3]], [])])
def test_arrangement_rejects_impossible_input(strategy, seeds, free):
    with pytest.raises(ValueError):
        strategy.arrange(seeds, free, 4, MeetingHistory())


def test_greedy_avoids_known_repeats():
    h = MeetingHistory()
    h.record([1, 2])
    h.record([3, 4])
    groups = GreedyMixingArrangement(random.Random(0)).arrange([], [1, 2, 3, 4], 2, h)
    assert sum(h.group_cost(g) for g in groups) == 0


def test_greedy_finds_a_second_round_with_no_repeats():
    h = MeetingHistory()
    greedy = GreedyMixingArrangement(random.Random(0))
    for _ in range(2):
        groups = greedy.arrange([], list(range(1, 17)), 4, h)
        for g in groups:
            h.record(g)
    assert h.repeated_meetings() == 0


def test_greedy_mixes_better_than_random_over_many_rounds():
    def repeats(strategy_cls):
        total = 0
        for seed in range(20):
            h, s = MeetingHistory(), strategy_cls(random.Random(seed))
            for _ in range(5):
                for g in s.arrange([], list(range(1, 17)), 4, h):
                    h.record(g)
            total += h.repeated_meetings()
        return total

    assert repeats(GreedyMixingArrangement) < repeats(RandomArrangement) / 2


# ---------- SeatingPlanner ----------
def planner(config, seed=0):
    rng = random.Random(seed)
    return SeatingPlanner(config, GreedyMixingArrangement(rng), rng)


def contenders_per_table(plan, contenders):
    return [sum(p in contenders for p in t.players) for t in plan.tables]


def test_contenders_are_packed_g_per_table():
    contenders = frozenset(range(1, 9))
    plan = planner(TournamentConfig(12, 3, 4)).plan(1, contenders, MeetingHistory())
    assert sorted(contenders_per_table(plan, contenders)) == [0, 4, 4]


def test_leftover_contenders_share_one_mixed_table():
    contenders = frozenset(range(1, 7))
    plan = planner(TournamentConfig(12, 3, 4)).plan(1, contenders, MeetingHistory())
    assert sorted(contenders_per_table(plan, contenders)) == [0, 2, 4]


def test_surplus_contenders_get_byes_and_everyone_else_plays():
    contenders = frozenset(range(1, 21))
    plan = planner(TournamentConfig(20, 2, 4)).plan(1, contenders, MeetingHistory())
    assert len(plan.byes) == 12 and not plan.resting
    assert contenders_per_table(plan, contenders) == [4, 4]


def test_resting_players_are_those_who_played_most():
    h = MeetingHistory()
    h.record([7, 8])  # 7 and 8 have played, everyone else has not
    plan = planner(TournamentConfig(10, 2, 4)).plan(2, frozenset({1, 2}), h)
    assert plan.resting == {7, 8}


def test_every_table_is_full_and_nobody_is_seated_twice():
    config = TournamentConfig(13, 3, 4)
    plan = planner(config).plan(1, frozenset({1, 2, 3, 4, 5}), MeetingHistory())
    seated = [p for t in plan.tables for p in t.players]
    assert len(plan.tables) == 3 and all(len(t.players) == 4 for t in plan.tables)
    assert len(seated) == len(set(seated))
    assert set(seated) | plan.byes | plan.resting == set(config.players)


# ---------- Report ----------
def test_mixing_report():
    h = MeetingHistory()
    h.record([1, 2, 3])
    h.record([1, 2, 4])
    report = mixing_report(h, [1, 2, 3, 4], champion=1, rounds=2)
    assert report.average_distinct_opponents == pytest.approx((3 + 2 + 2) / 3)
    assert report.fewest_distinct_opponents == 2
    assert report.repeated_meetings == 1
    assert report.max_possible_opponents == 3
