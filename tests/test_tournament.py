"""Testing there is always one champion and full tables (200 random tournaments)."""
import pytest

from tournament.models import TournamentConfig
from tournament.tournament import TournamentNotFinishedError
from tests.tournament_fakes import (LowestIdWins, NonContenderWins, OutsideWinner, RecordingObserver,
                                    make_tournament)

CONFIGS = [(8, 2, 4), (12, 3, 4), (13, 3, 4), (40, 5, 4), (20, 2, 4), (30, 3, 5), (9, 4, 2), (6, 1, 6)]


def test_deterministic_winner_becomes_champion():
    result = make_tournament(TournamentConfig(40, 5, 4), selector=LowestIdWins()).run()
    assert result.champion == 1


@pytest.mark.parametrize("n, t, g", CONFIGS)
@pytest.mark.parametrize("seed", range(25))
def test_random_tournament_always_finds_exactly_one_champion_with_all_tables_full(n, t, g, seed):
    config = TournamentConfig(n, t, g)
    result = make_tournament(config, seed).run()

    assert result.champion in config.players
    previous = frozenset(config.players)
    for r in result.rounds:
        plan = r.plan
        seated = [p for table in plan.tables for p in table.players]
        assert len(plan.tables) == t and all(len(table.players) == g for table in plan.tables)
        assert len(seated) == len(set(seated))
        assert set(seated) | plan.byes | plan.resting == set(config.players)
        assert r.contenders_before == previous and r.contenders_after <= previous  # never re-enter
        previous = r.contenders_after
    assert previous == {result.champion}


def test_title_race_resolves_in_a_logarithmic_number_of_eliminating_rounds():
    result = make_tournament(TournamentConfig(64, 16, 4), selector=LowestIdWins()).run()
    assert len(result.rounds) == 3  # 64 -> 16 -> 4 -> 1


def test_no_champion_within_round_limit_raises():
    holder = {}
    tournament = make_tournament(TournamentConfig(8, 2, 4), selector=NonContenderWins(lambda: holder["t"].contenders))
    holder["t"] = tournament
    with pytest.raises(TournamentNotFinishedError):
        tournament.run(max_rounds=10)


def test_winner_who_did_not_play_is_rejected():
    with pytest.raises(ValueError):
        make_tournament(TournamentConfig(8, 2, 4), selector=OutsideWinner()).play_round()


def test_cannot_play_after_champion_is_found():
    tournament = make_tournament(TournamentConfig(8, 2, 4), selector=LowestIdWins())
    tournament.run()
    with pytest.raises(RuntimeError):
        tournament.play_round()


def test_observers_see_every_round():
    observer = RecordingObserver()
    result = make_tournament(TournamentConfig(12, 3, 4), observers=[observer]).run()
    assert observer.results == list(result.rounds)


def test_greedy_seating_meets_more_people_than_random_seating():
    def total_distinct(arrangement):
        total = 0
        for seed in range(30):
            config = TournamentConfig(16, 4, 4)
            t = make_tournament(config, seed, arrangement=arrangement)
            t.run()
            total += t.history.repeated_meetings()
        return total

    assert total_distinct("greedy") < total_distinct("random")
