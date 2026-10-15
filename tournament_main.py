"""Composition root for the game-night tournament.

    python tournament_main.py --players 14 --tables 3 --seats 4 --seed 3        # one tournament, round by round
    python tournament_main.py --players 40 --tables 5 --seats 4 --compare 200   # greedy vs random seating
"""
from __future__ import annotations

import argparse
import random
from statistics import mean

from tournament.arrangement import GreedyMixingArrangement, RandomArrangement
from tournament.elimination import ContenderMustBeatContenderRule
from tournament.models import RoundResult, TournamentConfig
from tournament.outcomes import RandomWinnerSelector
from tournament.planner import SeatingPlanner
from tournament.report import mixing_report
from tournament.tournament import RoundObserver, Tournament

ARRANGEMENTS = {"greedy": GreedyMixingArrangement, "random": RandomArrangement}


class PrintingObserver(RoundObserver):
    """Prints each round. Marks contenders, lists byes, resting players and who was eliminated."""
    def on_round(self, result: RoundResult) -> None:
        plan = result.plan
        print(f"\nRound {plan.number}  (contenders: {len(result.contenders_before)})")
        for table, winner in zip(plan.tables, result.winners):
            seats = " ".join(f"{p:>3}{'*' if p in result.contenders_before else ' '}" for p in table.players)
            print(f"  table {table.number}: {seats}  -> winner {winner}")
        if plan.byes:
            print(f"  byes (contenders sitting out): {sorted(plan.byes)}")
        if plan.resting:
            print(f"  resting: {sorted(plan.resting)}")
        print(f"  eliminated from title race: {sorted(result.eliminated) or '-'}")


def build(config: TournamentConfig, seed: int, arrangement: str, observers=()) -> Tournament:
    rng = random.Random(seed)
    planner = SeatingPlanner(config, ARRANGEMENTS[arrangement](rng), rng)
    return Tournament(config, planner, RandomWinnerSelector(rng), ContenderMustBeatContenderRule(), observers=observers)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players", type=int, default=40, help="N participants")
    parser.add_argument("--tables", type=int, default=5, help="T tables")
    parser.add_argument("--seats", type=int, default=4, help="G players per table")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--arrangement", choices=ARRANGEMENTS, default="greedy")
    parser.add_argument("--compare", type=int, metavar="RUNS", help="compare arrangements over many tournaments")
    args = parser.parse_args()
    config = TournamentConfig(args.players, args.tables, args.seats)

    if args.compare:
        for name in ARRANGEMENTS:
            reports = []
            for seed in range(args.compare):
                t = build(config, seed, name)
                result = t.run()
                reports.append(mixing_report(t.history, config.players, result.champion, len(result.rounds)))
            print(f"{name:>7}: rounds {mean(r.rounds for r in reports):5.2f} | "
                  f"avg distinct opponents {mean(r.average_distinct_opponents for r in reports):5.2f} | "
                  f"repeated meetings {mean(r.repeated_meetings for r in reports):6.2f}")
        return

    print(f"N={config.participants} players, T={config.tables} tables, G={config.seats_per_table} seats "
          f"(* = still in the title race)")
    tournament = build(config, args.seed, args.arrangement, observers=[PrintingObserver()])
    result = tournament.run()
    report = mixing_report(tournament.history, config.players, result.champion, len(result.rounds))
    print(f"\nCHAMPION: player {result.champion} after {report.rounds} rounds")
    print(f"Average distinct opponents (non-winners): {report.average_distinct_opponents:.2f} "
          f"of max {report.max_possible_opponents}; fewest: {report.fewest_distinct_opponents}; "
          f"repeated meetings: {report.repeated_meetings}")


if __name__ == "__main__":
    main()
