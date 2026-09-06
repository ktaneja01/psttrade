"""Rebuild CRUDE_W pipeline: load hourly → daily → roll calendar → multiple → adjusted."""
import subprocess, sys

INSTRUMENT = "CRUDE_W"

# 1. Load hourly CSVs
from syscore.dateutils import HOURLY_FREQ
from sysdata.csv.csv_futures_contract_prices import ConfigCsvFuturesPrices
from sysinit.futures.contract_prices_from_csv_to_db import (
    init_db_with_csv_futures_contract_prices_for_code,
)
print(f"\n[1/4] Loading hourly CSVs into DB for {INSTRUMENT}...")
cfg = ConfigCsvFuturesPrices(
    input_date_index_name="Time",
    input_date_format="%Y-%m-%dT%H:%M:%S",
    input_skiprows=0, input_skipfooter=0,
    input_column_mapping=dict(OPEN="Open", HIGH="High", LOW="Low",
                              FINAL="Latest", VOLUME="Volume"),
)
init_db_with_csv_futures_contract_prices_for_code(
    INSTRUMENT, "/tmp/databento_hourly", csv_config=cfg, frequency=HOURLY_FREQ,
)

# 2. Derive daily from hourly
print(f"\n[2/4] Deriving daily prices from hourly...")
from syscore.dateutils import HOURLY_FREQ, DAILY_PRICE_FREQ, MIXED_FREQ
from sysproduction.data.prices import diagPrices
import pandas as pd

diag = diagPrices()
db = diag.db_futures_contract_price_data
contracts = [c for c in db.get_contracts_with_price_data_for_frequency(HOURLY_FREQ)
             if c.instrument_code == INSTRUMENT]
print(f"  Found {len(contracts)} hourly contracts")

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

# 3. Build roll calendar
print(f"\n[3/4] Building roll calendar...")
from sysinit.futures.rollcalendars_from_db_prices_to_csv import build_and_write_roll_calendar
try:
    build_and_write_roll_calendar(
        INSTRUMENT,
        output_datapath="/tmp/roll_calendars",
        check_before_writing=False,
    )
except Exception as e:
    print(f"  ERROR: {e}")
    sys.exit(1)

# 4. Build multiple and adjusted prices
print(f"\n[4/4] Building multiple + adjusted prices...")
from sysinit.futures.multipleprices_from_db_prices_and_csv_calendars_to_db import (
    process_multiple_prices_single_instrument,
)
try:
    process_multiple_prices_single_instrument(INSTRUMENT, ADD_TO_DB=True, ADD_TO_CSV=False)
except Exception as e:
    print(f"  ERROR: {e}")
    sys.exit(1)

print(f"\nDone.")
