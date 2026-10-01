# Production architecture — two fully-separated branches

Two independent pipelines with **no shared mutable state**. Each owns its data,
roll calendars, and artifacts. Neither writes to the shared repo
`data/futures/roll_calendars_csv/` (that global default caused 166 files to churn
and the two pipelines to clobber each other — now eliminated).

```
                RESEARCH  (experiment)                 LIVE  (production)
        ┌──────────────────────────────┐      ┌──────────────────────────────┐
        │  production/research/          │      │  production/live/             │
        │  • Try candidate instruments   │      │  • FROZEN production universe  │
        │  • Vendor data (BC + DB)       │      │  • Full history + IB live tail │
        │  • Grows freely (93, 100, ...) │      │  • Idempotent, reproducible    │
        │  • Freezes handcraft+scalars   │      │  • The store the system TRADES │
        └──────────────────────────────┘      └──────────────────────────────┘
                        │  PROMOTE (deliberate, manual):
                        │   frozen universe list + handcraft_weights + scalars
                        └────────────────────────────────►
```

## Why separated
- **Research** changes constantly (adding/dropping instruments to evaluate). It must
  never be able to corrupt what the live system trades.
- **Live** must be a **byte-reproducible, idempotent** rebuild: same inputs → same
  store, every run, no git pollution, no manual surgery. It only changes when you
  *deliberately promote* a new frozen universe/artifacts from research.

## Branch 1 — RESEARCH  (`production/research/`)
Purpose: decide what instruments earn a production slot.
- Universe: experimental, in `research/config.json` (superset — everything under test).
- Data: vendor only (Barchart core-api + Databento), cutoff configurable.
- Roll calendars: **store-local** `research/roll_calendars/` (via dot-free alias).
- Pipeline: `01_stage_raw → 02_curate → 03_roll_audit → 04_dq_gate → 05_freeze_handcraft → 06_freeze_scalars → 07_backtest`.
- Output: `research/artifacts/{handcraft_weights,forecast_scalars}.txt` + backtest.

## Branch 2 — LIVE  (`production/live/`)
Purpose: the idempotent store the live system makes trade decisions from.
- Universe: **FROZEN** in `live/config.json` — a deliberate subset promoted from research.
- Data: **full backtest history (seed) + IBKR live data → today**. Skew (13-month
  lookback) runs off the deep history; trades off the live tail.
- Roll calendars: **store-local** `live/roll_calendars/`.
- Build (**MIGRATED to stock, 2026-09-24**): the custom `01_fetch_ibkr` /
  `02_curate_rolladjusted` / `03_append_ib` scripts have been **retired** — they
  duplicated pysystemtrade's shipped daily price pipeline (proven byte-stable).
  The live data path is now stock `run_daily_price_updates`
  (`update_historical_prices` → `update_multiple_adjusted_prices`) with rolls via
  `interactive_update_roll_status`; QA is the remaining `03_roll_audit → 04_dq_gate`.
  See `MIGRATION_TO_STOCK.md`. (Retired scripts backed up at
  `/tmp/retired_live_scripts_2026-09-24/`; also recoverable from git history.)

## The seam that must never break (append-only)
`02_build` seeds from the research/backtest curated store (frozen historical rows)
and appends ONLY IB rows dated after each contract's last seed date. Historical rows
are never re-derived (that bug shifted CARRY and drifted 2019-2025 P&L — see memory).

## Promotion (research → live), the ONLY coupling
A manual, reviewed step:
1. In research, finalize the universe + backtest is satisfactory.
2. Copy the frozen universe list + `handcraft_weights.txt` + `forecast_scalars.txt`
   into `live/config.json` / `live/artifacts/` and into `signals.py`.
3. Rebuild `live/` store. Nothing in research can change `live/` without this step.

## What is NOT here (deferred to go-live execution)
Roll *status* flags, order stack, position limits live in **MongoDB** via the shipped
`sysproduction` daily loop — that's live *execution* state, separate from these
reproducible *price* stores. These branches produce the price data + config the
execution loop consumes.

## Layout (migration complete, 2026-09)
- `production/research/` — the research branch (was `production/backtest/`).
- `production/live/` — the live branch (was `production/ibkr/`; scripts evolved to
  isolated roll calendars + research seed, and the built 87-instrument IB store +
  roll calendars were moved in). This is the authoritative live store.
- Removed as legacy: `production/ibkr/` (superseded by `live/`),
  `production/ibkr_pipeline/`, `production/candidates/`.

Promotion DONE (2026-09): `live/config.json` universe is **114** = research's 117
minus the 3 deliberate venue-duplicates (`EURIBOR-ICE`, `JGB`, `PLN`). Frozen
handcraft weights + forecast scalars are consumed from `production/research/artifacts/`.

Data-currency note (2026-09-19): the 3 livestock instruments (`FEEDCOW`, `LEANHOG`,
`LIVECOW`) had gone stale at early-2020 in the live store. IB *fetch* was fine (raw
had data to 2026-09-17); the *append* kept rebuilding from stale 2020
`futures_contract_prices`. Because `03_append_ib.py` rebuilds adjusted/multiple FROM
the contract prices and seeds from the live store itself (`SEED = CUR`), a stale
contract-price seed never self-heals — and re-seeding only the derived adjusted/multiple
is reverted by the next append. Fix: re-seed `futures_contract_prices` (the SOURCE) from
`research/`, then run the append → livestock now current to 2026-08-17 (roll frontier).
Also fixed 19 `currency:"nan"` entries in `ib_contract_map` (from `instrumentconfig.csv`).
