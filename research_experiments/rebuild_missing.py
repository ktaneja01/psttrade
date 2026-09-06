"""Rebuild pipeline for 9 new instruments.
Step 1: Download missing (PLN, BRE, ETHANOL) via raw_symbol + parent.
Step 2: Load all hourly CSVs into DB.
Step 3: Derive daily from hourly.
Step 4: Build roll calendars + multiple prices + adjusted prices.
"""
import os, sys
from pathlib import Path
import pandas as pd

NEW_INSTRUMENTS = ["SP400", "INR", "PLN", "BRE", "ALUMINIUM",
                   "WHEAT", "CORN", "SOYBEAN", "ETHANOL"]

# ============================================================
# Step 1: Download missing — use parent symbology (like main script)
# ============================================================
missing_download = []
for inst in NEW_INSTRUMENTS:
    n_files = len(list(Path("data/databento/hourly").glob(f"Hour_{inst}_*.csv")))
    if n_files == 0:
        missing_download.append(inst)

if missing_download:
    print(f"\n[1/4] Downloading missing: {missing_download}")
    import databento as db
    from download_databento import INSTRUMENTS, download_instrument, load_priced_cycles
    api_key = os.environ.get("DATABENTO_API_KEY")
    if not api_key:
        sys.exit("DATABENTO_API_KEY not set")
    client = db.Historical(key=api_key)
    priced_cycles = load_priced_cycles()
    for inst in missing_download:
        if inst not in INSTRUMENTS:
            print(f"  {inst}: not in download_databento.py INSTRUMENTS — skipping")
            continue
        root = INSTRUMENTS[inst]
        cycle = priced_cycles.get(inst)
        if not cycle:
            print(f"  {inst}: no PricedRollCycle — skipping")
            continue
        print(f"  {inst} ({root}, cycle={cycle})...")
        download_instrument(inst, root, client, cycle)

    # Fix filename year bugs
    print("\nFixing filename year bugs...")
    os.system("pst-env/bin/python fix_databento_filenames.py 2>&1 | tail -5")
else:
    print("\n[1/4] All instruments have CSV files — skipping download")

# ============================================================
# Step 2: Load hourly CSVs into DB
# ============================================================
print(f"\n[2/4] Loading hourly CSVs for {len(NEW_INSTRUMENTS)} instruments...")
from syscore.dateutils import HOURLY_FREQ, DAILY_PRICE_FREQ, MIXED_FREQ
from sysdata.csv.csv_futures_contract_prices import ConfigCsvFuturesPrices
from sysinit.futures.contract_prices_from_csv_to_db import (
    init_db_with_csv_futures_contract_prices_for_code,
)

cfg = ConfigCsvFuturesPrices(
    input_date_index_name="Time",
    input_date_format="%Y-%m-%dT%H:%M:%S",
    input_skiprows=0, input_skipfooter=0,
    input_column_mapping=dict(OPEN="Open", HIGH="High", LOW="Low",
                              FINAL="Latest", VOLUME="Volume"),
)
for inst in NEW_INSTRUMENTS:
    print(f"  {inst}...")
    try:
        init_db_with_csv_futures_contract_prices_for_code(
            inst, "/tmp/databento_hourly", csv_config=cfg, frequency=HOURLY_FREQ,
        )
    except Exception as e:
        print(f"    ERROR: {e}")

# ============================================================
# Step 3: Derive daily from hourly
# ============================================================
print(f"\n[3/4] Deriving daily from hourly...")
from sysproduction.data.prices import diagPrices
diag = diagPrices()
db = diag.db_futures_contract_price_data
for inst in NEW_INSTRUMENTS:
    contracts = [c for c in db.get_contracts_with_price_data_for_frequency(HOURLY_FREQ)
                 if c.instrument_code == inst]
    if not contracts:
        print(f"  {inst}: 0 contracts in DB, skipping")
        continue
    print(f"  {inst}: {len(contracts)} contracts")
    for contract in contracts:
        hourly = db.get_prices_at_frequency_for_contract_object(contract, frequency=HOURLY_FREQ)
        if len(hourly) == 0:
            continue
        grouped = hourly.groupby(hourly.index.date)
        last_idx = grouped.apply(lambda g: g.index[-1])
        daily = hourly.loc[list(last_idx.values)]
        if len(daily) > 0:
            db.write_prices_at_frequency_for_contract_object(
                contract, futures_price_data=daily,
                ignore_duplication=True, frequency=DAILY_PRICE_FREQ,
            )
        db.write_prices_at_frequency_for_contract_object(
            contract, futures_price_data=hourly,
            ignore_duplication=True, frequency=MIXED_FREQ,
        )

# ============================================================
# Step 4: Build roll calendar + multiple + adjusted prices
# ============================================================
print(f"\n[4/4] Building roll calendars + multiple + adjusted prices...")
from sysinit.futures.rollcalendars_from_db_prices_to_csv import build_and_write_roll_calendar
from sysinit.futures.multipleprices_from_db_prices_and_csv_calendars_to_db import (
    process_multiple_prices_single_instrument,
)
from sysinit.futures.adjustedprices_from_db_multiple_to_db import (
    process_adjusted_prices_single_instrument,
)
import shutil

for inst in NEW_INSTRUMENTS:
    print(f"\n  === {inst} ===")
    # Remove stale parquets (force fresh rebuild)
    for pq in [f"/usr/local/bc_data/futures_multiple_prices/{inst}.parquet",
               f"/usr/local/bc_data/futures_adjusted_prices/{inst}.parquet"]:
        if os.path.exists(pq):
            os.remove(pq)

    # Roll calendar
    try:
        build_and_write_roll_calendar(inst, output_datapath="/tmp/roll_calendars",
                                      check_before_writing=False)
    except Exception as e:
        print(f"    ROLL CAL ERROR: {type(e).__name__}: {e}")
        continue

    # Copy to the location multi-prices builder reads
    src = f"/tmp/roll_calendars/{inst}.csv"
    dst = f"data/futures/roll_calendars_csv/{inst}.csv"
    if os.path.exists(src):
        shutil.copy(src, dst)

    try:
        process_multiple_prices_single_instrument(inst, ADD_TO_DB=True, ADD_TO_CSV=False)
    except Exception as e:
        print(f"    MULT PRICES ERROR: {type(e).__name__}: {e}")
        continue

    try:
        process_adjusted_prices_single_instrument(inst, ADD_TO_DB=True, ADD_TO_CSV=False)
    except Exception as e:
        print(f"    ADJ PRICES ERROR: {type(e).__name__}: {e}")

# ============================================================
# Summary
# ============================================================
print(f"\n\n{'=' * 60}")
print("SUMMARY — adjusted prices available")
print(f"{'=' * 60}")
for inst in NEW_INSTRUMENTS:
    adj = f"/usr/local/bc_data/futures_adjusted_prices/{inst}.parquet"
    if os.path.exists(adj):
        s = pd.read_parquet(adj).squeeze().dropna()
        print(f"  {inst:12s}  {len(s):>6d} rows  {s.index[0].date()} → {s.index[-1].date()}")
    else:
        print(f"  {inst:12s}  NO ADJUSTED PRICES")
