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
- Build: `01_fetch_ibkr → 02_build (seed+append, append-only) → 03_roll_audit → 04_dq_gate`.
- Idempotent: re-running `02_build` from the same seed + IB raw reproduces the store.

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

## Migration from current layout
- `production/backtest/`  → becomes `production/research/` (rename; it already is the research branch).
- `production/ibkr/`      → becomes `production/live/` (rename; fix roll-cal isolation + sync universe).
- `production/candidates/`, `production/ibkr_pipeline/` → legacy, archive/remove.
