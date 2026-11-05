# collections-portfolio-health-monitor

**Live-book collections monitoring, done the way a collections analyst actually works it: follow the whole merchant arrears book month over month — who is rolling deeper, who is curing, whose promises hold — put explicit early-risk flags on the names that need attention, then grade those flags against what happened next.**

Scoring a loan at origination is a different job from working a live book. Once accounts are on the book, the craft is **portfolio-health monitoring** — watching the whole portfolio's health move, not judging one application. The signals are monthly and behavioural: **delinquency buckets** — the arrears stages an account sits in (current, 1–30 days past due, 31–60, 61–90, 90+, write-off); **roll rates** — the share of one bucket that moves to another bucket next month, the book's pulse; **cure rates** — the share of delinquent accounts that come back to current; and **promise-to-pay (PTP)** — a delinquent merchant's commitment to pay an agreed amount, whose kept/broken record is the earliest warning there is. This project builds that whole monthly loop on a seeded synthetic merchant book, with two auditable flag rules instead of a black-box model, a **backtest** — grading yesterday's flags against the outcomes that followed — and a balance-conservation invariant that accounts for every dollar, every month, to the cent.

> **Synthetic data only.** Every merchant is fictional and every figure is fabricated by a seeded generator. No real company, merchant, or loan data is used anywhere in this project.

Stdlib-only Python. Zero network, zero API keys, zero external dependencies.

## How this differs from its sibling projects

> **collections-risk-scorer scores one loan at a time, credit-retrospective-kit looks backwards at closed vintages, this one monitors the live book.**

- **collections-risk-scorer** — per-loan **credit scoring** — judging a single application or account on its own features, at a point in time.
- **credit-retrospective-kit** — a backward-looking **vintage analysis** — grouping closed cohorts by their origination period to judge how past underwriting performed.
- **collections-portfolio-health-monitor (this repo)** — **live-book monitoring** — the current, still-moving book, followed month over month: buckets, rolls, cures, promises, and flags on names that are deteriorating *now*, while there is still time to act.

The three answer different questions — "should we book this loan?", "how did past cohorts turn out?", "what needs attention in the book this month?" — and none of them substitutes for another.

## Quickstart

```bash
# 1. Generate the synthetic merchant book (60 merchants x 12 months, seed 42)
python3 cli.py generate --out book.json

# 2. Monitor: bucket summary per month + cure rates
python3 cli.py monitor --input book.json

# 3. Roll-rate matrix: counts and balance-weighted rates, all transitions
python3 cli.py roll --input book.json

# 4. Promise-to-pay tracking + cure rates
python3 cli.py promises --input book.json

# 5. Early-risk flags + their backtest (the headline numbers)
python3 cli.py flags --input book.json

# 6. The monthly readout (markdown, not a dashboard)
python3 cli.py report --input book.json

# 7. CI gate: exit 0 = pass, 1 = flag-quality breach (backtest
#    precision / recall below floor), 2 = data-quality / IO error
#    (any balance-conservation violation lands here)
python3 cli.py check --input book.json

# 8. One-command end-to-end demo (incl. a live serve round-trip)
python3 demo.py

# 9. Tiny localhost API: POST /flags, GET /report, GET /health
python3 cli.py serve --port 8765
```

## The seeded book at a glance (seed 42, 60 merchants, 2025-01 → 2025-12)

**720 snapshots.** Total balance **$1,700,204.46 → $1,203,450.19** over the year — the book shrinks because the ten planted deteriorators are eventually written off and the ten planted curers pay down. The generator plants six **archetypes** — behavioural patterns given to groups of merchants so the signals are real, not noise:

| Archetype | Merchants | Planted behaviour |
|---|---|---|
| stable_current | 18 | current every month |
| stable_delinquent | 8 | parked in 1-30 every month |
| deteriorating | 10 | worsens one bucket a month to 90+ / write-off |
| curing | 10 | starts at 61-90, steps back to current |
| cyclical | 8 | bounces current ↔ 1-30, never two bad months running |
| stressed_recovering | 6 | worsens twice to 31-60, then cures — the planted false alarm |

Latest month: 34 merchants current ($842,449.88), 16 in 1-30 ($361,000.31), 10 written off ($0). Overall **promise kept rate 0.4907** (79 kept / 161 made) and overall **cure rate 0.2593** (56 cures / 216 delinquent transitions).

Roll rates (count %, all 660 transitions) — read a row as "of the accounts in this bucket, where did they go next month?":

| From \ To | current | 1-30 | 31-60 | 61-90 | 90+ | write-off |
|---|---|---|---|---|---|---|
| current | 84.0 | 16.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 1-30 | 35.0 | 55.0 | 10.0 | 0.0 | 0.0 | 0.0 |
| 31-60 | 0.0 | 61.5 | 0.0 | 38.5 | 0.0 | 0.0 |
| 61-90 | 0.0 | 0.0 | 50.0 | 0.0 | 50.0 | 0.0 |
| 90+ | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 |
| write-off | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 |

## The flags — and their backtest

Two explicit rules. No **scoring model** — a fitted statistical model that outputs a risk number (deliberately out of scope; a collections team can argue with a rule in a review meeting, and these two fit on an index card):

- **R1 — two-consecutive-worsening** — the bucket rose in each of the last two monthly transitions (e.g. current → 1-30 → 31-60).
- **R2 — broken-promise-with-growth** — the merchant is at least 31-60, broke a promise-to-pay this month, *and* the balance grew versus last month.

Backtest grading — a flag only counts as an **early warning** if it was raised while the merchant was still below 60+ with a full two months of follow-up left:

- **Precision** — of the flags graded, the share whose merchant really reached 60+ within two months: **0.625** (10 true / 16 graded).
- **Recall** — of the merchants who ever reached 60+, the share flagged in the two months before: **1.0** (10 / 10).

The six false positives are exactly the planted stressed_recovering merchants — names that looked like deteriorators for two months, then cured. A backtest with precision 1.0 on planted data would be a claim nobody should trust; 0.625 with named, explicable false alarms is the honest number, and it is pinned by golden eval E4 so it cannot quietly drift.

## Balance conservation — every dollar accounted for

**Balance conservation** — an accounting check that no money appears or disappears unexplained. Each snapshot row carries its flows (**charges** — new amounts added to the balance; **payments** — amounts paid down; **write-off amount** — balance removed when an account is written off), balances are *derived* from flows (`balance = prev_balance + charges − payments − write_off_amount`, to the cent), and validation, the test suite, and eval E2 all re-assert the identity independently for every merchant and every month, plus that the per-bucket balances sum to the book total. Tamper with one balance by $10 in a test and the check fires — that failure path is itself tested.

## Architecture

| Module | Job |
|---|---|
| `generator.py` | Deterministic synthetic book: 60 fictional merchants, 12 monthly snapshots, six planted archetypes; flows generated first, balances derived |
| `validation.py` | Data-quality gate (fields, buckets, duplicates, promise consistency) + the balance-conservation check; reports issues, never raises on bad data |
| `monitor.py` | Bucket summary per month, roll-rate matrix (count-based and **balance-weighted** — transitions weighted by the from-month balance, so big merchants count more), cure rates, promise-to-pay summary |
| `flags.py` | The two early-risk rules (R1, R2) + the backtest (precision / recall against rolling to 60+ within two months) |
| `report.py` | The markdown monthly readout, copied from the computed numbers; also the JSON companion payload |
| `cli.py` | `generate` / `monitor` / `roll` / `promises` / `flags` / `report` / `check` (CI exit 0/1/2) / `demo` / `serve` (stdlib `http.server` on 127.0.0.1: `POST /flags`, `GET /report`, `GET /health`) |
| `demo.py` | End-to-end narrative with asserts: determinism, conservation, backtest, check exit codes, live localhost serve round-trip |
| `fixtures/` | The full seeded book (`sample_book.json`) with pinned totals |

## Evals

`python3 evals/run_evals.py` → **11/11 golden evals**, report committed at `evals/eval_report.json` (md5 `60ec393cbb508bfc74f566cd978f10dd`, byte-identical across 3 verified runs):

- **E1** generator determinism — seed 42 dataset bytes pinned by md5
- **E2** balance conservation holds all 12 months; a tampered balance trips it
- **E3** roll matrix reconciles (660 transitions counted once, rate rows sum to 100%)
- **E4** headline backtest pinned (precision 0.625, recall 1.0, 10 TP / 6 FP)
- **E5** every planted deteriorator flagged (10/10)
- **E6** stable / curing / cyclical merchants never flagged
- **E7** promises + cures pinned (kept 79/161, cured 56/216)
- **E8** CLI `check` exit codes 0 / 1 / 2
- **E9** serve round-trip matches local flags + report exactly
- **E10** bundled fixture pinned (720 snapshots, latest total $1,203,450.19, validates clean)
- **E11** report determinism — markdown identical across independent builds

Unit tests: `python3 -m unittest discover -s tests` → **48 hermetic tests**, including a no-network enforcement test (sockets stubbed), hand-computed roll/cure/promise cases on a two-merchant book, both flag rules with their negative cases, conservation tamper tests, validation defects, CLI exit codes, and serve round-trips.

## Development loop — design decisions the checks validated

No fabricated war stories: the suite caught no production bug in the monitoring logic, and this section does not invent one. What it did do is pin three design decisions so they cannot silently rot:

1. **R2 does not fire at 1-30, on purpose — and a hand-built test proves why it must not.** A broken promise at 1-30 is common noise: the cyclical merchants bounce through 1-30 all year and cure the next month. The first rule draft was reviewed against that pattern before any code shipped: requiring *at least 31-60 plus balance growth* alongside the broken promise is what keeps the quiet book quiet (eval E6: zero flags on stable/curing/cyclical merchants), at the accepted cost of flagging a deteriorator one month later than the shallowest possible rule would.
2. **Precision is allowed to be 0.625.** The stressed_recovering archetype exists specifically so the backtest has real false positives to count. If a future change "improves" precision to 1.0 by absorbing those names into a rule exception, eval E4 fails — the metric is pinned to the honest value, not the flattering one.
3. **Balances are derived from flows, never chosen.** An early design sketch picked each month's balance from a growth factor and split flows afterwards to fit; rounding made that ordering fragile at the cent level. The shipped generator picks charges/payments first and derives the balance, so conservation holds by construction — and validation still re-asserts it independently, because "by construction" is a claim, not a check.

## Scope and honest limits

- **No scoring model.** Flags are two explicit rules with named thresholds, graded by backtest — not a probability of default. Adding a fitted model is the obvious next step and would have to beat 0.625 / 1.0 on this same backtest to earn its place.
- **No vintage / cohort curves.** This book is followed as one live portfolio; accounts are not grouped by origination cohort (that is the retrospective kit's job, above).
- **No strategy optimisation.** The monitor says which names need attention; it does not decide treatments, offers, or contact strategies, and it does not claim the flags cause the cures.
- **No dashboard.** The readout is one deterministic markdown page per run — the format a monthly portfolio review actually circulates.
- **Write-off is absorbing and final** in the generator: no recoveries, no re-aging, no partial charge-offs. Real books have all three; each would be a new flow type in the conservation identity.
- **The API is a demo surface.** It binds 127.0.0.1 only, holds its book in memory, and resets on restart.

## Why this project

It takes the author's target craft — collections and portfolio analytics, the world of his day job's portfolio-analyst transition — and shows the live half of it: not scoring yesterday's applications, but standing over a moving book every month, knowing which way each bucket is rolling, whose promises are breaking, and whether your own early warnings were worth raising. The same discipline a forward-deployed engineer brings to a customer problem: make the logic inspectable, make the outputs reproducible, and make the failure modes exit codes.
