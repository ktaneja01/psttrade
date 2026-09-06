"""Ingest 7 new bc-utils instruments with 10yr history: AEX, BTP, BUXL,
EURIBOR, HANG, OAT, SMI. Follows the same pipeline as rebuild_bcutils.py."""
import os, shutil
from syscore.dateutils import HOURLY_FREQ, DAILY_PRICE_FREQ, MIXED_FREQ
from sysdata.csv.csv_futures_contract_prices import ConfigCsvFuturesPrices
from sysinit.futures.contract_prices_from_csv_to_db import init_db_with_csv_futures_contract_prices_for_code
from sysinit.futures.rollcalendars_from_db_prices_to_csv import build_and_write_roll_calendar
from sysinit.futures.multipleprices_from_db_prices_and_csv_calendars_to_db import process_multiple_prices_single_instrument
from sysinit.futures.adjustedprices_from_db_multiple_to_db import process_adjusted_prices_single_instrument
from sysproduction.data.prices import diagPrices

INSTRUMENTS = ["AEX", "BTP", "BUXL", "EURIBOR", "HANG", "OAT", "SMI"]

cfg = ConfigCsvFuturesPrices(
    input_date_index_name="Time",
    input_date_format="%Y-%m-%dT%H:%M:%S",
    input_skiprows=0, input_skipfooter=0,
    input_column_mapping=dict(OPEN="Open", HIGH="High", LOW="Low",
                              FINAL="Latest", VOLUME="Volume"),
)
diag = diagPrices()
db = diag.db_futures_contract_price_data

print("[1/4] Loading hourly CSVs...")
for inst in INSTRUMENTS:
    print(f"  {inst}...", flush=True)
    try:
        init_db_with_csv_futures_contract_prices_for_code(
            inst, "/tmp/barchart_data", csv_config=cfg, frequency=HOURLY_FREQ)
    except Exception as e:
        print(f"    ERROR: {e}", flush=True)

print("\n[2/4] Deriving daily from hourly...", flush=True)
for inst in INSTRUMENTS:
    contracts = [c for c in db.get_contracts_with_price_data_for_frequency(HOURLY_FREQ)
                 if c.instrument_code == inst]
    print(f"  {inst}: {len(contracts)} contracts", flush=True)
    for c in contracts:
        hourly = db.get_prices_at_frequency_for_contract_object(c, frequency=HOURLY_FREQ)
        if len(hourly) == 0:
            continue
        grp = hourly.groupby(hourly.index.date)
        daily = hourly.loc[list(grp.apply(lambda g: g.index[-1]).values)]
        if len(daily) > 0:
            db.write_prices_at_frequency_for_contract_object(
                c, futures_price_data=daily, ignore_duplication=True,
                frequency=DAILY_PRICE_FREQ)
        db.write_prices_at_frequency_for_contract_object(
            c, futures_price_data=hourly, ignore_duplication=True,
            frequency=MIXED_FREQ)

print("\n[3/4] Building roll calendars...", flush=True)
for inst in INSTRUMENTS:
    print(f"  {inst}...", flush=True)
    try:
        build_and_write_roll_calendar(inst, output_datapath="/tmp/roll_calendars",
                                      check_before_writing=False)
        src = f"/tmp/roll_calendars/{inst}.csv"
        dst = f"data/futures/roll_calendars_csv/{inst}.csv"
        if os.path.exists(src):
            shutil.copy(src, dst)
    except Exception as e:
        print(f"    ERROR: {e}", flush=True)

print("\n[4/4] Building multiple + adjusted prices...", flush=True)
for inst in INSTRUMENTS:
    for pq in [f"/usr/local/bc_data/futures_multiple_prices/{inst}.parquet",
               f"/usr/local/bc_data/futures_adjusted_prices/{inst}.parquet"]:
        if os.path.exists(pq):
            os.remove(pq)
    print(f"  {inst}...", flush=True)
    try:
        process_multiple_prices_single_instrument(inst, ADD_TO_DB=True, ADD_TO_CSV=False)
        process_adjusted_prices_single_instrument(inst, ADD_TO_DB=True, ADD_TO_CSV=False)
        # Verify
        if os.path.exists(f"/usr/local/bc_data/futures_adjusted_prices/{inst}.parquet"):
            print(f"    OK adjusted_prices parquet created", flush=True)
        else:
            print(f"    WARN no adjusted prices parquet", flush=True)
    except Exception as e:
        print(f"    ERROR: {e}", flush=True)

print("\nDONE", flush=True)
