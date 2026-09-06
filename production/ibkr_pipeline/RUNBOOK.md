# IBKR production data pipeline — RUNBOOK (verified 2026-08-28)

Wires IBKR as the live price source using pysystemtrade's **shipped** `sysbrokers/IB`
stack (NOT the hand-rolled `ibkr_fetch.py`). Verified end-to-end: brought the
81-instrument live universe current to 2026-08 by appending IB data onto the
existing parquet seed. **Result: 81/81 current.**

## Key architecture facts (why this is simpler than the old HYBRID_PIPELINE.md feared)
- **Production price store IS parquet at `/usr/local/bc_data`** — the SAME store the
  backtest seed lives in (`production_data_objects.py:76` maps
  FUTURES_CONTRACT_PRICE_DATA → `parquetFuturesContractPriceData`). So "append IB
  onto the seed" is the shipped default, not a custom seam. No arctic/Mongo for prices.
- **Only metadata needs MongoDB**: contract-sampling state, roll state,
  process control, client-id locks, order stacks. Prices/FX/multiple/adjusted = parquet.
- **IB pull is `duration="1 Y"` backward from today** (`ib_price_client.py`), NOT
  start-date-bounded. Today−1yr covers Jan-2026 with margin. The incremental merge
  (`merge_data_keeping_past_data.py`) keeps only rows AFTER each contract's last
  stored date → "from Jan 2026 onward" is automatic, no code change.
- **All 81 instruments are in the shipped `ib_config_futures.csv`** (0 missing),
  including every EU/US sector, IG, MSCISING, FTSECHINAA.
- Rolling is SEPARATE from the daily append (see `## Rolling`).

## Prerequisites (one-time)
1. **MongoDB** (self-contained tarball — avoid brew, it wants Xcode + 16 upgrades):
   ```
   # already installed at ~/mongodb-macos-aarch64-7.0.14/
   ~/mongodb-macos-aarch64-7.0.14/bin/mongod \
     --dbpath ~/mongodb-data --logpath ~/mongodb-log/mongod.log \
     --port 27017 --bind_ip 127.0.0.1 &
   ```
   Ping: `pst-env/bin/python3 -c "import pymongo; print(pymongo.MongoClient().admin.command('ping'))"`
2. **IB Gateway** (paper) listening on **4002** (live=4001). Paper account = `DUR997745` (DU-prefix).
3. **private_config.yaml** (`private/`):
   ```
   parquet_store: '/usr/local/bc_data'   # DOT-FREE path (resolver turns dots→slashes; ~/foo.bar breaks!)
   mongo_host: 'localhost'
   mongo_db: 'production'
   ib_ipaddress: '127.0.0.1'
   ib_port: 4002
   broker_account: 'DUR997745'
   ```

## The shipped daily pipeline (what to run)
Both accept a scoped instrument list programmatically (avoid the interactive prompt):
```python
# 1. sample which contracts to pull (writes Mongo futures_contracts)
from sysproduction.update_sampled_contracts import update_active_contracts_for_instrument
# 2. pull IB bars, append to parquet per-contract store (both intraday + daily)
from sysproduction.update_historical_prices import (
    update_historical_prices_for_list_of_instrument_codes,   # scoped
    update_historical_prices_for_instrument)                 # single
# 3. rebuild multiple + adjusted from updated contracts (no_roll — pure append)
from sysproduction.update_multiple_adjusted_prices import update_multiple_adjusted_prices_for_instrument
```
Production scheduler entry points (for cron): `run_daily_price_updates.py` then
`run_daily_update_multiple_adjusted_prices.py`.

## Safety protocol (used for the 2026-08 run)
1. Snapshot: `tar czf ~/bc_data_backups/bc_data_snapshot_DATE.tgz -C /usr/local bc_data`
2. Dry-run copy to a **dot-free** path: `cp -R /usr/local/bc_data /tmp/bc_data_dryrun`,
   point `parquet_store` there, validate, THEN rsync back:
   `rsync -a /tmp/bc_data_dryrun/{futures_adjusted_prices,futures_multiple_prices,futures_contract_prices}/ /usr/local/bc_data/<same>/`
3. Restore `parquet_store: '/usr/local/bc_data'` after.

## Rolling (occasional, NOT daily)
Daily `update_multiple_adjusted_prices` uses `update_with_multiple_prices_NO_ROLL`
— pure append, never advances the priced-contract pointer or re-shifts history.
A roll is a discrete event when the priced contract nears expiry:
```python
from sysproduction.reporting.data.rolls import rollingAdjustedAndMultiplePrices
obj = rollingAdjustedAndMultiplePrices(data, code, allow_forward_fill=True)
_ = obj.updated_multiple_prices; obj.write_new_rolled_data()
```
Panama math: at roll, `roll_differential = FORWARD − PRICE` (prev row) is ADDED to
ALL prior adjusted history, new contract price appended (`adjusted_prices.py:70-135`).
So the whole series shifts by the gap ONLY on a roll day; normal days just append.
(NOTE: importing `interactive_update_roll_status` fails on a scipy/statsmodels
`_lazywhere` mismatch → import `rollingAdjustedAndMultiplePrices` directly instead.)

## Gotchas hit (2026-08)
- **Seed months behind → batch roll needed.** A months-old seed has many priced
  pointers pointing at already-expired contracts. `update_multiple_adjusted_prices`
  (no_roll) can't fix them; they need iterative `Roll_Adjusted` (forward-fill) to
  advance to a live contract, THEN append.
- **Seeding aborts on expired priced contract** (IB expiry lookup fails) → the
  instrument's recent contracts never register in Mongo → roll says "Contract X not
  found" even though the parquet data exists. Fix: register+sample directly
  (`dataContracts.add_contract_data` + `.mark_contract_as_sampling`), then roll.
- **Spike check**: `max_price_spike: 8.0` (defaults.yaml, vol-normalised units).
  Merges with >8σ moves at the join are REJECTED (return SPIKE_IN_DATA), warned to
  log for `interactive_manual_check_historical_prices`. Daily merge usually still lands.
- **Seam is mostly clean**: measured IB-vs-seed on 40 live-contract overlaps →
  32 clean (<0.5%), the rest low-overlap noise. NIKKEI's apparent −2% "jump" was a
  benign hourly-seed-vs-daily-IB comparison artifact, not a real discontinuity.
- **IB shallow history (~2-3yr)**: names whose seed ended >2yr ago (HANG_mini,
  AEX_mini ended 2024-03) CANNOT be bridged by IB (only reaches back ~2026-01).
  Rebuild those from Barchart (`Hour_<CODE>_*.csv` at `~/data/barchart`, note
  HANG_mini←HANG, AEX_mini←AEX) via the notebook rebuild chain. See /tmp/rebuild_2mini.py.

## Final state 2026-08-28
81/81 live-universe instruments current to Aug-2026 in `/usr/local/bc_data`.
Snapshot pre-run: `~/bc_data_backups/bc_data_snapshot_2026-08-28.tgz`.
