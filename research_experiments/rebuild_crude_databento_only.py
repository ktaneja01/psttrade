"""CRUDE_W: clear ALL DB entries, re-ingest databento-only, rebuild calendar + parquet."""
import os, shutil
from syscore.dateutils import HOURLY_FREQ, DAILY_PRICE_FREQ, MIXED_FREQ
from sysdata.csv.csv_futures_contract_prices import ConfigCsvFuturesPrices
from sysinit.futures.contract_prices_from_csv_to_db import init_db_with_csv_futures_contract_prices_for_code
from sysinit.futures.rollcalendars_from_db_prices_to_csv import build_and_write_roll_calendar
from sysinit.futures.multipleprices_from_db_prices_and_csv_calendars_to_db import process_multiple_prices_single_instrument
from sysinit.futures.adjustedprices_from_db_multiple_to_db import process_adjusted_prices_single_instrument
from sysproduction.data.prices import diagPrices

INSTRUMENT = "CRUDE_W"

diag = diagPrices()
db = diag.db_futures_contract_price_data

print(f"[0/4] Purging ALL CRUDE_W contract data from DB...", flush=True)
for freq in [HOURLY_FREQ, DAILY_PRICE_FREQ, MIXED_FREQ]:
    try:
        db.delete_prices_at_frequency_for_instrument_code(
            instrument_code=INSTRUMENT, frequency=freq, areyousure=True)
        print(f"  Cleared {freq} data", flush=True)
    except Exception as e:
        print(f"  {freq}: {e}", flush=True)

# Also purge old parquet + roll calendar
for pq in [f"/usr/local/bc_data/futures_multiple_prices/{INSTRUMENT}.parquet",
           f"/usr/local/bc_data/futures_adjusted_prices/{INSTRUMENT}.parquet"]:
    if os.path.exists(pq):
        os.remove(pq)
for rc in [f"/tmp/roll_calendars/{INSTRUMENT}.csv",
           f"data/futures/roll_calendars_csv/{INSTRUMENT}.csv"]:
    if os.path.exists(rc):
        os.remove(rc)
print("  Cleared parquet + roll calendar files", flush=True)

print(f"\n[1/4] Loading DATABENTO hourly CSVs for {INSTRUMENT}...", flush=True)
cfg = ConfigCsvFuturesPrices(
    input_date_index_name="Time",
    input_date_format="%Y-%m-%dT%H:%M:%S",
    input_skiprows=0, input_skipfooter=0,
    input_column_mapping=dict(OPEN="Open", HIGH="High", LOW="Low",
                              FINAL="Latest", VOLUME="Volume"),
)
init_db_with_csv_futures_contract_prices_for_code(
    INSTRUMENT, "/tmp/databento_hourly", csv_config=cfg, frequency=HOURLY_FREQ)

print(f"\n[2/4] Deriving daily from hourly...", flush=True)
contracts = [c for c in db.get_contracts_with_price_data_for_frequency(HOURLY_FREQ)
             if c.instrument_code == INSTRUMENT]
print(f"  {len(contracts)} contracts", flush=True)
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

print(f"\n[3/4] Building roll calendar...", flush=True)
try:
    build_and_write_roll_calendar(INSTRUMENT, output_datapath="/tmp/roll_calendars",
                                  check_before_writing=False)
    src = f"/tmp/roll_calendars/{INSTRUMENT}.csv"
    dst = f"data/futures/roll_calendars_csv/{INSTRUMENT}.csv"
    if os.path.exists(src):
        shutil.copy(src, dst)
        print(f"  OK roll calendar written", flush=True)
except Exception as e:
    print(f"  ERROR: {e}", flush=True)

print(f"\n[4/4] Building multiple + adjusted prices...", flush=True)
try:
    process_multiple_prices_single_instrument(INSTRUMENT, ADD_TO_DB=True, ADD_TO_CSV=False)
    process_adjusted_prices_single_instrument(INSTRUMENT, ADD_TO_DB=True, ADD_TO_CSV=False)
    if os.path.exists(f"/usr/local/bc_data/futures_adjusted_prices/{INSTRUMENT}.parquet"):
        print("  OK CRUDE_W parquet created from databento-only data", flush=True)
    else:
        print("  WARN still missing", flush=True)
except Exception as e:
    print(f"  ERROR: {e}", flush=True)

print("\nDONE", flush=True)
