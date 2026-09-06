# Project map — custom pysystemtrade setup

This is a fork of pysystemtrade (Rob Carver's systematic futures engine) with a
custom multi-rule strategy and data pipeline layered on top via **root-level
scripts**. The `sys*/` package dirs are mostly upstream; the customization lives
in the root `.py` files. This file is the map of that customization.

## Master strategy config — `signals.py`

The central, current production configuration. **Every portfolio sleeve script
`exec`s it.** Don't reconstruct the config elsewhere — read `signals.py`.

- Capital $500K (env `CAPITAL`), **25%** annual vol target, data from 2018-01-01.
  (Reverted 30%→25% in 2026-06: the 30% bump "to compensate for dyn-opt integer
  rounding" backfired at smaller capital — more churn/tracking error. Vol sweep
  at $250K: 30%→SR 0.50, 25%→0.71, 20%→0.745.)
- **28 trading rules across 3 families**, all frozen (no runtime estimation):
  - **Trend 45%** (12 rules @ 3.75%): `spot_trend` 8_32/16_64/32_128/64_256,
    `accel` 8/16/32/64, `breakout` 20/40/80/160
  - **Carry 45%** (12 rules @ 3.75%): `carry` 10/30/60/125,
    `relcarry` 10/30/60/125, `carry_accel` 10/30/60/125
  - **Skew 10%** (4 rules @ 2.5%): `skewabs` 180/365, `skewrv` 180/365
- **60 instruments** across 6 asset classes, after a `bad_markets` filter.
  Recent (2026-06): **GOLD → GOLD_micro** (granularity at low capital; a pure
  duplicate, Sharpe-neutral), and **+IG** (iBoxx investment-grade credit) added
  to Bonds as a new credit-spread factor (~0.83→0.87 Sharpe). `BITCOIN`,
  `ETHEREUM`, `ETHER-micro` were relabelled `Metals → Crypto` in
  `instrumentconfig.csv` (they were polluting the Metals `skewrv` cross-section).
- Frozen knobs: `FROZEN_SCALARS` (forecast scalars), forecast weights, and
  `FROZEN_HANDCRAFT_SHRUNK_WEIGHTS` (instrument weights). All
  `use_*_estimates = False`. Vol attenuation on for all rules. Cost ceiling
  0.10 annualized SR per (rule, instrument).

## Instrument allocation — handcraft_shrunk (hierarchical vol)

How risk is split across instruments. Carver's `handcraft_optimisation`
(`sysquant/optimisation/optimisers/handcraft.py`):

- Computed once on full sample by **`freeze_handcraft_weights.py`**, then the
  printed `FROZEN_HANDCRAFT_SHRUNK_WEIGHTS = {…}` dict is pasted into
  `signals.py:319` and consumed with `use_instrument_weight_estimates = False`
  (`signals.py:351-352`). To refresh weights: re-run that script, paste the dict.
- Method: weekly returns from 2016 → correlation matrix **shrunk 50% toward
  average** → binary correlation tree → top-down **equal risk per branch** →
  **inverse-vol at leaves** → **5% cap** with redistribution.
  `equalise_SR=True`, `equalise_vols=True`.
- **Returns are engine-consistent** (2026-06 fix): `diff(adjusted)/carry_price`,
  NOT `pct_change` on the adjusted level. The panama-adjusted level can go
  negative for long contango/backwardation series (energy) — that's fine, the
  engine never uses the level (`rawdata.daily_denominator_price` = raw carry
  price). Using `pct_change` on the level gives 1000%+ garbage vol and corrupts
  the tree — the old bug behind the "exclude energy" mistake.
- 6 asset classes: Bonds, Grains, Energy-Livestock, Equity-Risk, G10-FX,
  EM-Metal-Crypto. Net effect ≈ 1/6 risk per class, inverse-vol within, ≤5% each.
- Research-only alternatives (NOT wired into signals.py): `herc_k7.py` (HERC
  K=7), `herc_depth2.py` (HERC binary depth 2), `show_shrinkage_weights.py`
  (shrinkage optimiser), `handcraft_tree.py` / `plot_handcraft_dendrogram.py`
  (visualize the cluster tree).

## Portfolio sleeves (all wrap signals.py)

- `four_sleeve_portfolio.py` — $750K: SPY $250K + System $250K + Gold $125K + Cash $125K
- `three_sleeve_portfolio.py` — $500K: SPY 50% / Gold 20% / System 30%, 20% vol
- `two_sleeve_spy.py` — $500K: SPY 50% / System 50%

Standalone (NOT part of the main system):
- `vix_contango_strategy.py` — $250K regime-gated VIX short/long, eVRP (GARCH) + vol-of-vol sizing
- `vix_carry_backtest.py` — $100K, single `carry90` on VIX only

## Data pipeline — bc-utils (Barchart)

Barchart price downloads via **bc-utils**, cloned at **`~/bc-utils`** (separate
venv `~/bc-utils/.venv`).

- Config: `~/bc-utils/private_config.yaml` — credentials, ~60-instrument
  `barchart_download_list` (== `barchart_update_list`), `barchart_path:
  /Users/kunal.taneja/data/barchart`, years 2016–2026.
- Download script `~/bc-utils/sample/pst.py`: `download_with_config()` fetches
  new/missing contracts; `update_with_config()` refreshes existing files (only
  appends new rows — idempotent).
- **Gotcha:** stock `update_with_config()` has NO per-instrument error handling,
  so a single transient Barchart 500 aborts the whole loop. Prefer a resilient
  runner that wraps each instrument in try/except and can resume from a given
  instrument. (Allowance counter shown as `ratelimit N` in logs; Premier resets
  per session.)
- Load CSVs into PST DB: see `docs/data.md`. Older custom load scripts
  (`load_bcutils_hourly.py`, `rebuild_bcutils.py`) read from `/tmp/barchart_data`
  and use `Latest` (not `Close`) as FINAL.

## bc-utils → adjusted-prices rebuild recipe (verified)

Turning today's raw bc-utils CSVs into backtest-ready adjusted prices. Two
non-obvious gotchas make the naive approach silently produce zero data:

1. **Stage to a DOT-FREE path** (e.g. `/tmp/barchart_data`), don't read
   `~/data/barchart` directly. pysystemtrade resolves csv datapaths as *package*
   paths via `resolve_path_and_filename_for_package`, so the `.` in the home dir
   `/Users/kunal.taneja/...` is turned into `/` → `/Users/kunal/taneja/...` →
   **0 files found, no error**. This is why all the load scripts use
   `/tmp/barchart_data`.
2. **Strip the `+0000` timezone** from the `Time` column before loading. Files
   mix tz-aware and tz-naive rows; the loader parses `+0000` to UTC then drops
   tz and re-parses, failing on the format. `sed 's/+0000//'` (or regex
   `[+-]\d{4}`) fixes it.
3. Use the **hourly loader** (NOT the split-freq loader — that needs Day_ files,
   but `barchart_do_daily: False` means only `Hour_` files exist). Config:
   `ConfigCsvFuturesPrices(input_date_index_name="Time",
   input_date_format="%Y-%m-%dT%H:%M:%S", FINAL="Latest")`.

Pipeline per instrument: stage+strip → `init_db_with_csv_futures_contract_prices_for_code(..., frequency=HOURLY_FREQ)`
→ derive daily from hourly (groupby date, last) + write MIXED_FREQ →
`build_and_write_roll_calendar` (copy to `data/futures/roll_calendars_csv/`) →
`process_multiple_prices_single_instrument` → `process_adjusted_prices_single_instrument`.
Roll-calendar generation is the fragile per-instrument step (IndexError when no
contracts). A self-healing version is in
`notebooks/handcraft_and_backtest.ipynb` (`rebuild_from_bcutils`).

## Notebook: handcraft visual + backtest

`notebooks/handcraft_and_backtest.ipynb` — steps through handcraft_shrunk
(dendrogram + weight chart, vs frozen weights) and runs the live-config backtest.
Self-heals data: restores `/tmp/parquet` from repo CSV stores, then rebuilds any
universe instrument missing from the snapshot (e.g. TECDAX, which isn't in the
committed repo CSVs). Reuses signals.py via the
`split("# Build system with dynamic optimisation")[0]` seam. Kernel: `pst-env`
(ipykernel installed there).
- **Step 0c — data-quality preflight**: scans every adjusted-price file and
  *quarantines* crash-risk instruments (empty/stale/<60 post-start obs) to
  `/tmp/parquet/_quarantine` so the relative-skew rule doesn't abort with
  "No adjusted daily prices for X". Warns on suspect data.
- **Step 0d — roll-integrity test**: checks `multiple_prices` for backward rolls,
  wrong-next-contract rolls, big roll-boundary gaps. (A negative adjusted *level*
  is NOT flagged — it's expected/harmless; see the engine-consistent-returns note.)

## Diagnostics / research scripts (read against the 28-rule set)

`oos_by_rule.py` (per-rule OOS Sharpe), `forecast_matrix.py` (latest forecasts),
`skew_standalone.py` / `skew_forecasts.py`, `strategy_stats.py`,
`compare_strategies.py`, `diagnose_breakout.py`, `turnover_accel8.py`.

**Caution:** some research scripts use older `ewmac8_32`-style naming and build
configs from scratch (NOT from signals.py): `compare_strategies.py`,
`relcarry_diagnostic.py` (misnamed — actually analyzes trend rules),
`diagnose_breakout.py` (adds non-standard `breakout320`). These are benchmarks,
not the live system.

## Recent fixes & gotchas (2026-06)

- **Cost-deflator stale-price bug (patched).** `calculate_cost_deflator` in
  `syscore/pandas/strategy_functions.py` vol-normalises trade costs by
  `vol(t)/final_vol`; a *stale price padded flat* to the backtest end drives
  `final_vol`→0 → deflator explodes (~600–950×) → huge phantom costs (a fake
  −$186k on GBPJPY in 2022). Fix: anchor `final_vol` to the last date the price
  actually moved. Feeds BOTH the accounting P&L costs and the dynamic-opt costs.
- **Trade-cost config is partly stale** (`spreadcosts.csv` is undated; some
  `PerBlock` values wrong: GBPJPY 359 vs FX ~2.7, GILT/TECDAX/ZINC_LME = 0).
  Re-sample from the broker and fix outliers **before productionising**.
- **Two correlation/shrinkage estimates** (don't conflate): handcraft *weights*
  shrink 50% toward the **average**; the dynamic-opt *tracking* covariance shrinks
  50% toward **zero** off-diagonal. Operative dyn-opt config (`defaults.yaml`
  `small_system`, not the dataclass defaults): `shadow_cost: 50`,
  `tracking_error_buffer: 0.0125`.
- **Data sources:** non-CME instruments + some micros come from bc-utils/Barchart
  (`~/bc-utils`); CME full-size (GOLD/COPPER/AUD, dense CNH) come from **Databento**
  (pipeline not in this repo). bc-utils CNH is too sparse to build. Much of the
  `/tmp/parquet` store ends ~2024-03 (stale) except recently-rebuilt names.
- **VIX overlay** lives at `~/vix_carry` (separate ML project). Correlation to
  this book: +0.08 (inverse-vol VIX sizing) vs +0.54 (decile-notional sizing).
