# Hybrid production data pipeline: frozen seed + IBKR append

## The constraint that defines this design
IBKR serves only ~2-3 years of futures daily history (TESTED 2026-08: ES=3yr,
ZN=17mo, MES=2yr — even requesting "15 Y"). **IB CANNOT provide the 2018-2026
history the backtest needs.** So production is HYBRID, not IB-replaces-vendor.

## Two layers
1. **FROZEN SEED (never re-fetched):** the existing `/usr/local/bc_data/` parquet
   store — Databento (CME) + bc-utils (non-CME) history 2018–2024. This is the deep
   history. IB has no replacement for it. Treat as read-only archive.
2. **LIVE APPEND (IBKR, daily):** from ~2024 onward, IBKR provides new daily bars
   via the SHIPPED `sysbrokers/IB` integration (NOT hand-rolled — see note below).

## Use the SHIPPED integration — do NOT reinvent
pysystemtrade ships the full IB stack; use it:
- `sysbrokers/IB/config/ib_config_futures.csv` — 585-instrument IB symbol map
  (ALL 74 of our instruments present + correct). Replaces our hand-rolled CONTRACT_MAP.
- `sysbrokers/IB/ib_futures_contract_price_data.py` — production IB price fetch.
- `sysbrokers/IB/ib_connection.py` — managed connection.
- REAL sysproduction entry points (verified present):
  - `run_daily_price_updates.py` / `update_historical_prices.py` — daily IB price pull
  - `run_daily_fx_and_contract_updates.py` — FX + contract sampling
  - `update_multiple_adjusted_prices.py` / `run_daily_update_multiple_adjusted_prices.py` — rebuild multiple+adjusted
  - `update_sampled_contracts.py` — which contracts to sample
  - `interactive_manual_check_historical_prices.py` — manual QA
  This IS the designed daily price-update process
  that drives the above into the price store (Mongo/parquet).
Our `production/ibkr_pipeline/ibkr_fetch.py` + resolvers were a learning exercise;
prefer the shipped code for production.

## The daily production loop (target)
```
[1] sysproduction update_historical_prices
       └─ sysbrokers/IB pulls recent daily bars per contract (ib_config_futures.csv)
       └─ APPENDS to the per-contract store (only new rows since last date)
[2] roll calendars auto-extend as contracts approach expiry
[3] rebuild multiple_prices + adjusted_prices (incremental) from updated contracts
[4] data_quality_gate.py  (../data_quality_gate.py) — QA before it feeds live
[5] signals.py builds system on updated store -> dyn-opt target positions
[6] diff target vs current IB positions (ib_contract_position_data) -> orders
[7] sysproduction order/execution stack (ib_orders) -> IB
[8] reconcile positions/P&L vs IB
```

## THE ONE HARD INTEGRATION PROBLEM: the seam
pysystemtrade's `update_historical_prices` expects to build history FROM IB. But IB
only has ~2yr. We must make it **append onto the frozen seed**, not rebuild from IB's
shallow window. Approaches:
- (a) Point the production price store at the existing parquet seed; IB update only
  writes NEW contracts / NEW rows (dates after the seed's last date). Verify the IB
  contract-price format matches the seed's schema so appends align.
- (b) Verify no ADJUSTMENT JUMP at the seam (~2024): IB back-adjustment vs the seed's
  panama stitch must be consistent, or the adjusted series gets a discontinuity.
  Spot-check a few instruments at the join date.

## Migration steps (from backtest-only to hybrid production)
1. Stand up MongoDB (pysystemtrade production state store).
2. Point production price data at the parquet seed (or migrate seed into the prod store).
3. Configure `sysbrokers/IB` connection (paper first: 127.0.0.1:4002).
4. Run `update_historical_prices` in APPEND mode; confirm it only adds post-seed rows.
5. Verify the seam (no adjusted-price jump at the 2024 join).
6. QA gate on the merged store.
7. Paper-trade the full loop ~1 month before live capital.

## Status of instruments (2026-08)
- All 74 in the shipped IB map (0 missing) — IB can serve recent data for all.
- Deep history: 72/74 have 2018-2026 seed; ZINC_LME/US-REALESTATE thinner.
- New adds this session (EU sectors, US sectors, KOSPI/KOSDAQ/TOPIX/JGB/CAD10) are
  IB-only short-history -> live-forward, no deep seed (accept short history for these).
