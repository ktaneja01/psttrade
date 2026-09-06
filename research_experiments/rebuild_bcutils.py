"""Build pipeline for 6 bc-utils instruments: BOBL, BUND, GILT, SHATZ, V2X, VIX."""
import os, shutil
import pandas as pd
from syscore.dateutils import HOURLY_FREQ, DAILY_PRICE_FREQ, MIXED_FREQ
from sysdata.csv.csv_futures_contract_prices import ConfigCsvFuturesPrices
from sysinit.futures.contract_prices_from_csv_to_db import init_db_with_csv_futures_contract_prices_for_code
from sysinit.futures.rollcalendars_from_db_prices_to_csv import build_and_write_roll_calendar
from sysinit.futures.multipleprices_from_db_prices_and_csv_calendars_to_db import process_multiple_prices_single_instrument
from sysinit.futures.adjustedprices_from_db_multiple_to_db import process_adjusted_prices_single_instrument
from sysproduction.data.prices import diagPrices

INSTRUMENTS = ["BOBL", "BUND", "GILT", "SHATZ", "V2X", "VIX"]

# bc-utils CSV config (same column/date format as Databento)
cfg = ConfigCsvFuturesPrices(
    input_date_index_name="Time",
    input_date_format="%Y-%m-%dT%H:%M:%S",
    input_skiprows=0, input_skipfooter=0,
    input_column_mapping=dict(OPEN="Open", HIGH="High", LOW="Low",
                              FINAL="Latest", VOLUME="Volume"),
)
diag = diagPrices()
db = diag.db_futures_contract_price_data

# 1. Load hourly CSVs from bc-utils directory
print("[1/4] Loading hourly CSVs from bc-utils into DB...")
for inst in INSTRUMENTS:
    print(f"  {inst}...")
    try:
        init_db_with_csv_futures_contract_prices_for_code(
            inst, "/tmp/barchart_data", csv_config=cfg, frequency=HOURLY_FREQ)
    except Exception as e:
        print(f"    ERROR: {e}")

# 2. Derive daily from hourly
print("\n[2/4] Deriving daily from hourly...")
for inst in INSTRUMENTS:
    contracts = [c for c in db.get_contracts_with_price_data_for_frequency(HOURLY_FREQ)
                 if c.instrument_code == inst]
    print(f"  {inst}: {len(contracts)} contracts")
    for c in contracts:
        hourly = db.get_prices_at_frequency_for_contract_object(c, frequency=HOURLY_FREQ)
        if len(hourly) == 0: continue
        grp = hourly.groupby(hourly.index.date)
        daily = hourly.loc[list(grp.apply(lambda g: g.index[-1]).values)]
        if len(daily) > 0:
            db.write_prices_at_frequency_for_contract_object(
                c, futures_price_data=daily, ignore_duplication=True,
                frequency=DAILY_PRICE_FREQ)
        db.write_prices_at_frequency_for_contract_object(
            c, futures_price_data=hourly, ignore_duplication=True,
            frequency=MIXED_FREQ)

# 3. Build roll calendars
print("\n[3/4] Building roll calendars...")
for inst in INSTRUMENTS:
    print(f"  {inst}...")
    try:
        build_and_write_roll_calendar(inst, output_datapath="/tmp/roll_calendars",
                                      check_before_writing=False)
        src = f"/tmp/roll_calendars/{inst}.csv"
        dst = f"data/futures/roll_calendars_csv/{inst}.csv"
        if os.path.exists(src):
            shutil.copy(src, dst)
    except Exception as e:
        print(f"    ERROR: {e}")

# 4. Build multiple + adjusted prices
print("\n[4/4] Building multiple + adjusted prices...")
for inst in INSTRUMENTS:
    for pq in [f"/usr/local/bc_data/futures_multiple_prices/{inst}.parquet",
               f"/usr/local/bc_data/futures_adjusted_prices/{inst}.parquet"]:
        if os.path.exists(pq): os.remove(pq)
    print(f"  {inst}...")
    try:
        process_multiple_prices_single_instrument(inst, ADD_TO_DB=True, ADD_TO_CSV=False)
        process_adjusted_prices_single_instrument(inst, ADD_TO_DB=True, ADD_TO_CSV=False)
    except Exception as e:
        print(f"    ERROR: {e}")

# Summary
print("\n\n=== SUMMARY ===")
for inst in INSTRUMENTS:
    adj = f"/usr/local/bc_data/futures_adjusted_prices/{inst}.parquet"
    if os.path.exists(adj):
        s = pd.read_parquet(adj).squeeze().dropna()
        print(f"  {inst:<8s} {len(s):>6d} rows  {s.index[0].date()} → {s.index[-1].date()}  "
              f"min={s.min():.2f} max={s.max():.2f}")
    else:
        print(f"  {inst:<8s} FAILED")
