#	Running proposed solution 

##	Run with Docker

```
docker compose build
docker compose run --rm tests                  		# full test suite run

docker compose up pipeline                     		# problem 1: demo (10 s windows); Ctrl+C to stop
docker compose run --rm pipeline python main.py		# problem 1: default settings (5 min windows, files nightly at 02:00); Ctrl+C to stop

docker compose run --rm tournament             		# problem 2: one tournament, round by round
docker compose run --rm tournament-compare     		# problem 2: greedy vs random seating

# custom arguments
docker compose run --rm tests python -m pytest tests/test_messaging.py -v                                   	# test suite: testing one file 
docker compose run --rm pipeline python main.py --files-now --strategy next-fit --files 200 --mean-file-mb 5	# problem 1: custom arguments; Ctrl+C to stop
docker compose run --rm tournament python tournament_main.py --players 40 --tables 5 --seats 4 --seed 7     	# problem 2: custom arguments 

```

Without Compose: `docker build -t mds-solution .`, then `docker run --rm mds-solution` (runs the tests)
or `docker run --rm -it mds-solution python main.py --window 10 --files-now` (runs problem 1 demo).

Stopping the pipeline container (`Ctrl+C` or `docker compose stop`) shuts it down gracefully: the open
minibatch is flushed and the worker pool finishes its queued work.

## Run locally

```
pip install -r requirements.txt
python -m pytest -v                                                     	# full test suite run

python main.py --window 10 --files-now                                  	# problem 1: demo (10 s windows); Ctrl+C to stop
python main.py                                                          	# problem 1: default settings (5 min windows, files nightly at 02:00); Ctrl+C to stop

python tournament_main.py --players 14 --tables 3 --seats 4 --seed 3    	# problem 2: one tournament, round by round
python tournament_main.py --players 40 --tables 5 --seats 4 --compare 200 	# problem 2: greedy vs random seating

# custom arguments
python -m pytest tests/test_messaging.py -v                                 	# test suite: testing one file
python main.py --files-now --strategy next-fit --files 200 --mean-file-mb 5 	# problem 1: custom arguments; Ctrl+C to stop
python tournament_main.py --players 40 --tables 5 --seats 4 --seed 7        	# problem 2: custom arguments


# generate documentation
pip install pdoc && pdoc pipeline tournament                                	# browse the API documentation
```

# Problem 1: Data processing pipeline

Two pipelines run in parallel and share one pool of 10 worker threads:

1. **Messages → minibatches.** A Poisson source (about 10 msgs/min) feeds `MinibatchService`. The first
   message opens a batch, and the batch holds every message stamped within the next 5 minutes. When the
   window closes, the batch is dispatched to the pool, even if no new message has arrived. Dispatching
   only enqueues, so forming the next batch never waits for earlier batches to be processed.
2. **Nightly files → buckets.** `DailyScheduler` runs `FileBucketingJob` every night. The job gathers 100
   files with exponentially distributed sizes, packs them into buckets of at most 10 MB using a pluggable
   `BucketingStrategy`, and dispatches each bucket.

```
PoissonMessageSource ─► MinibatchService ─(MessageBatch)─┐
                                                         ├─► WorkerPool(10) ─► WorkItemRouter ─► processors
DailyScheduler ─► FileBucketingJob ─(FileBucket)─────────┘
                    ├── FileSource            (SimulatedFileSource / DirectoryFileSource)
                    └── BucketingStrategy     (FirstFitDecreasingStrategy / NextFitStrategy)
```

## Layout ('pipeline/')

| Module | Contents |
|---|---|
| `core.py` | Abstractions: `Clock`, `Dispatcher`, `Processor`, `Job`, `BackgroundProcess` |
| `distributions.py` | `Distribution`, `ExponentialDistribution` |
| `messaging.py` | `Message`, `MessageBatch`, `MessageSource`, `PoissonMessageSource`, `TimeWindowAccumulator` (pure rules), `MinibatchService` |
| `files.py` | `FileDescriptor`, `FileBucket`, `FileSource` + implementations, `FileBucketingJob` |
| `bucketing.py` | `BucketingStrategy` + `NextFitStrategy`, `FirstFitDecreasingStrategy` |
| `workers.py` | `WorkerPool` (`ThreadPoolExecutor`), `WorkItemRouter` |
| `scheduling.py` | `DailyScheduler` |
| `main.py` | Composition root |

## SOLID

- **S**: Each class has one job. For example, the batching rules (`TimeWindowAccumulator`) are separate from the threading (`MinibatchService`).
- **O**: New strategies, sources and work types are added by writing a new class and registering it. No existing class needs editing.
- **L**: Every strategy must pass the same contract tests (`tests/test_bucketing.py`).
- **I**: The interfaces are small, mostly a single method.
- **D**: Components depend on abstractions that are injected in `main.py`. Time is injected too, so tests never wait for real minutes.

## Adding a bucketing strategy

```python
class MyStrategy(BucketingStrategy):
    def pack(self, files, capacity_bytes): ...
```
Then add it to `STRATEGIES` in `tests/test_bucketing.py` (so it must pass the contract tests) and in `main.py`.

# Problem 2: Game-night tournament

N players, T tables, G players per table, and one winner per game. The tournament ends when one
player is left in the title race.

Rules:
- Contenders sit G to a table, so each such table eliminates G-1 of them. Leftover contenders (fewer than G)
  share one mixed table. If contenders outnumber the seats, the extra ones get a bye.
- A contender is eliminated only when **another contender** wins at their table. The title race can never
  end with nobody left, and a champion is always found.
- Every other seat goes to eliminated players, those who have played least going first, so **all T tables
  are used every round**.
- Seating minimises repeated meetings. This is the Social Golfer Problem, which is NP-hard, so the seating
  is a heuristic rather than a proven optimum.
  
 One round:

```
                SeatingPlanner         who plays: contenders G per table, leftover contenders share
                      │                one table, extra contenders get a bye, free seats go to
                      │                eliminated players (fewest games played first)
                      ▼
              ArrangementStrategy      who sits with whom, minimising repeated meetings
                      │                (GreedyMixingArrangement / RandomArrangement)
                      ▼
                WinnerSelector         one winner per table (RandomWinnerSelector / SkillWeightedWinnerSelector)
                      │
                      ├──────────────► MeetingHistory    who has met whom; used by the next round's seating
                      ▼
               EliminationRule         ContenderMustBeatContenderRule
                      │
                      ▼
          one contender left? ── yes ─► champion
                      │
                      no ─► next round (back to SeatingPlanner)
```

Example: round 2 of a tournament with 14 players at 3 tables of 4 (`* = still in the title race`):

```
  table 1:  11*   8*   2*  10*    contenders only   → 8 wins, so 2, 10 and 11 are out of the title race
  table 2:  14*   9    1    7     mixed table       → 1 (already eliminated) wins, so 14 stays in
  table 3:   3    6   12    4     eliminated only   → the game only serves mixing
  resting:   5   13                                   (rotation: fewest games played go first)
```

## Layout (`tournament/`)

| Module | Contents |
|---|---|
| `models.py` | `TournamentConfig` (validates G >= 2, T >= 1, N >= T*G), `Table`, `RoundPlan`, `RoundResult`, `TournamentResult` |
| `history.py` | `MeetingHistory`: how often each pair played together, games played, distinct opponents |
| `outcomes.py` | `WinnerSelector` -> `RandomWinnerSelector`, `SkillWeightedWinnerSelector` |
| `elimination.py` | `EliminationRule` -> `ContenderMustBeatContenderRule` |
| `arrangement.py` | `ArrangementStrategy` -> `GreedyMixingArrangement` (greedy + swap local search), `RandomArrangement` |
| `planner.py` | `SeatingPlanner`: who plays, who sits out, which contenders share tables |
| `tournament.py` | `Tournament`: runs rounds until there is a champion; `RoundObserver` hook |
| `report.py` | `MixingReport`: distinct opponents and repeated meetings |
| `tournament_main.py` | Composition root |

##	SOLID:

- **S**: Each class has one job: who plays (`SeatingPlanner`), who sits where (`ArrangementStrategy`), who wins (`WinnerSelector`), who stays in (`EliminationRule`).
- **O**: New seating, winner or elimination rules are new classes; `Tournament` doesn't change.
- **L**: Both seating strategies (`GreedyMixingArrangement`, `RandomArrangement`) pass the same contract tests.
- **I**: Small interfaces, one method each.
- **D**: Everything is injected in `tournament_main.py`, including randomness, so any tournament can be replayed from its seed.

# Tests 

296 tests, about 1 second, no real waiting: time is faked and randomness uses fixed seeds.

```
tests/
├── fakes.py                              test doubles for problem 1
├── test_messaging.py               21    window rules, minibatch service, Poisson source
├── test_bucketing.py               16    contract tests run against every strategy + strategy examples
├── test_files.py                    9    files, file sources, FileBucketingJob
├── test_workers.py                  9    worker pool, WorkItemRouter
├── test_scheduling.py               6    next run time, nightly scheduler
├── test_system.py                   1    end to end: both pipelines on one shared pool
├── tournament_fakes.py                   test doubles for problem 2
├── test_tournament_components.py   27    config, history, elimination rule, winners, strategies, planner, report
└── test_tournament.py             207    whole tournaments, incl. 200 random ones (8 setups x 25 seeds)
```

## Layout (`tests/`)

| File | What it checks |
|---|---|
| `test_messaging.py` | 5-minute windows from the first message, boundary handling, batches don't wait for processing, Poisson statistics |
| `test_bucketing.py` | Every strategy keeps the 10 MB rule and packs each file once |
| `test_files.py` | File sources, and the job packs and dispatches every file |
| `test_workers.py` | At most 10 at once, non-blocking dispatch, failures isolated |
| `test_scheduling.py` | One run per night at 02:00, failures don't stop the schedule |
| `test_system.py` | Both pipelines on one shared pool |
| `test_tournament_components.py` | Each tournament class on its own: rules, seating, planner |
| `test_tournament.py` | Always one champion and full tables (200 random tournaments) |

**Test doubles**

| File | Doubles |
|---|---|
| `fakes.py` | `FakeClock`, `ManualMessageSource`, `FailingMessageSource`, `SequenceDistribution`, `InMemoryFileSource`, `files_of_sizes_mb`, `exponential_files`, `StubBucketingStrategy`, `RecordingDispatcher`, `RecordingProcessor`, `GatedProcessor`, `RecordingJob`, `running`, `wait_until` |
| `tournament_fakes.py` | `LowestIdWins`, `NonContenderWins`, `OutsideWinner`, `RecordingObserver`, `make_tournament` |

# Design decisions and trade-offs

## Problem 1: Data processing pipeline

- **Batches are decided by message timestamps, not arrival time.** A window is `[first message, +5 min)`.
  A message exactly at the end starts the next batch, so no message can end up in two batches, and the
  result doesn't depend on thread timing.
- **The batching rules are separate from the threading.** `TimeWindowAccumulator` is plain logic with no
  threads or clock, so it is tested directly. `MinibatchService` only runs the loop: a pump thread reads the
  source, and the loop waits for either the next message or the window deadline, whichever comes first.
- **Dispatching never blocks.** `dispatch` only submits to the pool, so a new batch is formed while earlier
  ones are still being processed. 10 workers are plenty: a batch arrives about every 5 minutes, so the
  pool only falls behind if one batch takes longer than about 50 minutes to process.
- **Time is injected (`Clock`).** Tests use a fake clock and don't wait real minutes. In production,
  stopping interrupts any sleep immediately.
- **Bucketing is a pluggable strategy.** Next-Fit is simple; First-Fit-Decreasing packs tighter. Optimal
  bin packing is NP-hard and not required. A file larger than 10 MB gets a bucket of its own.
- **Threads, not asyncio.** The task asks for a thread pool, and processing is usually blocking I/O. For
  CPU-heavy work the pool could be replaced by a process pool behind the same `Dispatcher` interface.
- **One shared pool for both pipelines**, as the task describes. The trade-off is that the nightly
  buckets can briefly delay minibatches; two separate pools would be a one-line change in `main.py`.

Known limitations and production notes: batches still queued in memory are lost if the process crashes,
and batch IDs are random, so a retry is not idempotent. In production I would read from Kafka, build
windows with event-time timers (Flink or Spark), use deterministic batch IDs and commit offsets after
processing, and run the nightly job from Airflow. The 2 MB mean file size is my assumption; the task only
says the sizes are exponential.

## Problem 2: Game-night tournament

- **Only a contender can eliminate a contender.** If an already eliminated player wins a table, the
  contenders there stay in. This guarantees the title race never ends with nobody left. With "any loss
  eliminates", two contenders at the same table can both lose to eliminated players.
- **Contenders are packed G to a table**, so each table removes G-1 of them and the champion is found in
  about log_G(N) rounds. Leftover contenders share one table so they can still meet; if there are more
  contenders than seats, the rest get a bye instead of being eliminated without playing.
- **Eliminated players keep playing** to fill the remaining seats, so every table is used every round.
  Whoever has played least goes first, so sitting out rotates fairly.
- **Who plays is separate from who sits with whom.** `SeatingPlanner` applies the tournament rules;
  `ArrangementStrategy` only optimises the mixing, so either can change on its own.
- **Mixing is a heuristic.** Maximising distinct opponents is the Social Golfer Problem (NP-hard). The
  greedy seating plus pairwise swaps gives about 4x fewer repeat meetings than random seating
  (40 players, 5 tables of 4, 200 tournaments).
- **Seating is planned round by round**, because who must sit together depends on results that aren't
  known in advance.

Known limitations: the seating is not provably optimal and optimises total repeats. The final stage can 
take a few extra rounds when eliminated players keep winning, and the history is kept in memory for a 
single tournament.