---
name: reseed-stale-instrument
description: >-
  Fix a stale/broken futures instrument in the live pysystemtrade store by
  re-seeding its contracts from IB and rebuilding roll calendar + multiple +
  adjusted prices. Use when an instrument's multiple-prices is frozen on
  EXPIRED contracts, or when you see "No contracts marked for sampling for X",
  ContractNotFound in check_key_contracts_have_not_expired, or the roll report
  flags an instrument whose priced contract has already expired (e.g.
  GAS_US_mini, EURIBOR). All stock sysproduction/sysinit — no custom pipeline.
---

# Re-seed a stale instrument from IB

## Symptom → this skill applies when
- `update_sampled_contracts` crashes with `ContractNotFound: X/<yyyymm>00` in
  `check_key_contracts_have_not_expired` (its instrument loop has NO per-instrument
  try/except, so one bad instrument aborts the whole universe).
- `interactive_manual_check_historical_prices` says **"No contracts marked for
  sampling for X"**.
- Roll report flags an instrument whose PRICE/FORWARD/CARRY contracts are all
  in the past.

## Root cause
The instrument's `futures_multiple_prices` is frozen on expired contracts. The
sampling chain is built FROM multiple-prices' furthest-out contract, so it only
ever sees expired contracts → no live contract is sampled → nothing to fetch, and
the roll-alarm can't find the (expired, un-registered) priced contract. Breaking
this needs a re-seed of the live contracts directly from IB, then a rebuild of the
roll/multiple/adjusted chain so PRICE_CONTRACT advances to a live contract.

## Prerequisites (verify first)
- MongoDB up (`pgrep -f mongod`) and IB Gateway up (`nc -z 127.0.0.1 4002`).
- `private/private_config.yaml` → `parquet_store` points at the **dot-free** live
  store (`/usr/local/bc_data`). A dotted path (`/Users/kunal.taneja/...`) is turned
  dots→slashes by the resolver → 0 files, silent no-op. This is the #1 gotcha.
- `PY=pst-env/bin/python3`, run from repo root.

## Procedure (set INST, e.g. GAS_US_mini)

### 1. Seed live+expired contracts from IB → futures_contract_prices
```bash
nohup bash -c 'echo "GAS_US_mini" | pst-env/bin/python3 -m sysinit.futures.seed_price_data_from_IB > /tmp/seed_reseed.log 2>&1' &
```
Fetches every contract IB lists (hourly+daily) and writes merged per-contract prices.
**Expected harmless noise:** `Error getting data` / `Error 200 No security definition`
for far-future (2030-31) and long-expired contracts IB has no data for. Wait for it
to finish (`pgrep -f seed_price_data_from_IB`), then confirm the live months landed:
```bash
pst-env/bin/python3 -c "import pandas as pd,glob;[print(c,pd.read_parquet(glob.glob(f'/usr/local/bc_data/futures_contract_prices/GAS_US_mini#{c}*.parquet')[0]).index.max()) for c in ['20261000','20261100','20261200']]"
```

### 2. Rebuild the roll calendar (dot-free out path — DON'T use the interactive __main__)
The stock `__main__` writes to the dotted shared repo path (resolver-hostile + churns
git). Call the function directly with a dot-free `output_datapath`:
```bash
mkdir -p /tmp/rc_reseed
pst-env/bin/python3 -c "
from sysinit.futures.rollcalendars_from_db_prices_to_csv import build_and_write_roll_calendar
build_and_write_roll_calendar('GAS_US_mini', output_datapath='/tmp/rc_reseed', check_before_writing=False)"
```
A trailing `Couldn't find matching roll date ... OK if happens at the end` warning is
the benign frontier effect.

### 3. Rebuild multiple prices from DB prices + calendar → writes to the store
```bash
pst-env/bin/python3 -c "
from sysinit.futures.multipleprices_from_db_prices_and_csv_calendars_to_db import process_multiple_prices_single_instrument
process_multiple_prices_single_instrument('GAS_US_mini', csv_roll_data_path='/tmp/rc_reseed', ADD_TO_DB=True, ADD_TO_CSV=False)"
```

### 4. Rebuild adjusted (panama) prices from multiple
```bash
pst-env/bin/python3 -c "
from sysinit.futures.adjustedprices_from_db_multiple_to_db import process_adjusted_prices_single_instrument
process_adjusted_prices_single_instrument('GAS_US_mini', ADD_TO_DB=True, ADD_TO_CSV=False)"
```

### 5. Re-sample — call the stock function DIRECTLY (not the interactive script)
The interactive `update_sampled_contracts` glitches on piped input (`EOFError`). Call
the per-instrument function directly and verify live contracts are now sampling:
```bash
pst-env/bin/python3 -c "
from sysdata.data_blob import dataBlob
from sysproduction.update_sampled_contracts import update_active_contracts_for_instrument
from sysproduction.data.contracts import dataContracts
d=dataBlob(log_name='reseed-sample')
try:
    update_active_contracts_for_instrument('GAS_US_mini', d); print('SAMPLING OK (no crash)')
except Exception as e: print('CRASH:', type(e).__name__, str(e)[:80])
print('sampled:', dataContracts(d).get_all_sampled_contracts('GAS_US_mini').list_of_dates())
d.close()"
```
**Success:** prints `SAMPLING OK` and a list of **live** contract dates (future months).
Expired months log `Contract is missing can't get expiry` and are correctly not sampled.

## After this
The instrument is current and sampling; the normal stock daily loop
(`run_daily_fx_and_contract_updates` → `run_daily_price_updates` →
`run_daily_update_multiple_adjusted_prices`) keeps it fresh, and the roll report
manages its front contract. No custom scripts added.

## WON'T WORK: STIRs with large negative RollOffsetDays (e.g. EURIBOR, SONIA3)
This procedure is for instruments that roll near expiry. It **fails** for STIRs that
roll ~2yr BEFORE expiry (EURIBOR `RollOffsetDays ≈ -700`). Confirmed on EURIBOR
(2026-09-26): IB re-seed brought contracts current, but the roll-calendar rebuild
(step 2) stalls — a contract in the chain (e.g. `20250300`) lacks the DEEP pre-2024
history needed to find concurrent prices at the −700-day roll point, and **IB only
serves ~2–3yr so it can't backfill it**. Truncating to 2024+ makes it worse: the −700
offset pushes every roll date before the truncation cutoff, collapsing them onto one
date (non-monotonic calendar). Symptom: "Couldn't find matching roll date ... 20241200,
20250300" NOT at the calendar end, and/or "Date index not monotonically increasing".
**Resolution:** don't rebuild from IB. Either (a) leave it deferred (a stale instrument
simply isn't sampled/traded — the dyn-opt tends to zero STIRs anyway, see stir-too-safe),
or (b) **backfill deep history from Barchart, then rebuild** (this WORKED for EURIBOR
2026-09-26 — recipe below). Do NOT change RollOffsetDays to force it — that alters the
strategy's contract selection. Stop at step 2 if you see this; the store is untouched
until step 3.

### Vendor (Barchart) deep-history backfill — worked for EURIBOR
Barchart (`~/data/barchart/Hour_<INST>_<yyyymm>00.csv`) holds ~5yr/contract, back to
2008–2010 — deep enough for the −700 roll. Recipe:
1. Back up the store's `<INST>#*.parquet` + multiple + adjusted first (e.g. to a dir
   under `~`).
2. Stage the plain `Hour_<INST>_*.csv` into a **dot-free** dir, stripping the tz:
   `sed -E 's/([0-9]{2}:[0-9]{2}:[0-9]{2})[+-][0-9]{4}/\1/'`. If a contract is MISSING
   from the plain set but exists as the venue-duplicate `Hour_<INST>-ICE_<cid>.csv`
   (same underlying), copy it in renamed to the plain name (EURIBOR's 20250300 gap).
3. `parquet_store` = the dot-free live store (`/usr/local/bc_data`); delete the store's
   existing `<INST>` prices at HOURLY/DAILY/MIXED, then
   `init_db_with_csv_futures_contract_prices_for_code(INST, <stage_dir>, csv_config, HOURLY_FREQ)`.
   csv_config: `ConfigCsvFuturesPrices(input_date_index_name='Time',
   input_date_format='%Y-%m-%dT%H:%M:%S', input_column_mapping={OPEN:Open,HIGH:High,
   LOW:Low,FINAL:Latest,VOLUME:Volume})`.
4. Derive daily per contract (last obs/day, `.normalize()` to 00:00) + write MIXED.
5. Steps 2–5 of the main procedure (roll calendar to a dot-free out dir → multiple →
   adjusted → re-sample).
Result: EURIBOR history 2008→2026-09-11, PRICE_CONTRACT advanced to a live 2028 front,
11 live contracts sampling. Barchart is ~2wk behind; the daily IB append tops up the tail.
(The far-end "couldn't find roll date" warning for the last 2028-29 contracts is the
benign frontier effect. Stage/roll-calendar dirs must be dot-free — the parquet resolver
turns dots→slashes; anywhere dot-free works, chosen at run time.)

## Gotchas recap
- **parquet_store must be dot-free** or every step silently no-ops.
- **Build roll calendar via the function + dot-free path**, never the dotted default.
- **Re-sample via the direct function call**, not the interactive script (EOFError).
- **Far-future / expired IB errors in step 1 are harmless** — the live months are what matter.
- STIRs (EURIBOR, SONIA3) hold contracts ~2yr out (large negative RollOffsetDays); the
  seed pulls far contracts fine, but expect more expired-contract noise.
