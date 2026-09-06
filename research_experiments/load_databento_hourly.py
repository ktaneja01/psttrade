"""Load Databento hourly OHLCV CSVs into pysystemtrade Parquet.

This is a thin wrapper around the same loader used for bc-utils data — the
Databento download script writes files in the exact bc-utils format, so the
only difference is the datapath.

Before running, ensure you've already run `download_databento.py` to populate
`data/databento/hourly/`.
"""
from syscore.dateutils import HOURLY_FREQ
from sysdata.csv.csv_futures_contract_prices import ConfigCsvFuturesPrices
from sysinit.futures.contract_prices_from_csv_to_db import (
    init_db_with_csv_futures_contract_prices_for_code,
)

# Same config as load_bcutils_hourly.py — FINAL="Latest" + ISO 8601 dates
databento_hourly_config = ConfigCsvFuturesPrices(
    input_date_index_name="Time",
    input_date_format="%Y-%m-%dT%H:%M:%S",
    input_skiprows=0,
    input_skipfooter=0,
    input_column_mapping=dict(
        OPEN="Open",
        HIGH="High",
        LOW="Low",
        FINAL="Latest",
        VOLUME="Volume",
    ),
)

datapath = "/tmp/databento_hourly"   # symlink → ~/pysystemtrade/data/databento/hourly (dot-free path for pysystemtrade's path resolver)

# Load only the instruments you want. Full list matches download_databento.py
instruments = [
    # Equity (6)
    "SP500", "NASDAQ", "RUSSELL", "DOW", "NIKKEI", "SP400",
    # Rates (10)
    "US2", "US3", "US5", "US10", "US10U", "US20", "US30",
    "SOFR", "SOFR1", "FED",
    # FX (15)
    "EUR", "JPY", "GBP", "AUD", "NZD", "MXP", "CHF",
    "CAD", "BRE", "ZAR", "PLN", "INR", "CNH-CME", "EURCHF", "GBPEUR",
    # Energy (9)
    "CRUDE_W", "GAS_US", "GASOILINE", "BRENT_W", "HEATOIL",
    "BRENT-LAST", "GAS-LAST", "GAS-PEN", "ETHANOL",
    # Metals (7)
    "GOLD", "SILVER", "COPPER", "PLAT", "PALLAD", "ALUMINIUM", "STEEL",
    # Grains (8)
    "WHEAT", "SOYBEAN", "SOYMEAL", "SOYOIL", "RICE", "OATIES", "CORN", "REDWHEAT",
    # Livestock / Dairy (6)
    "LEANHOG", "LIVECOW", "FEEDCOW", "MILK", "CHEESE", "BUTTER",
    # Crypto (3)
    "BITCOIN", "ETHEREUM", "BRR",
    # Lumber (1)
    "LUMBER-new",
]

for instrument_code in instruments:
    print(f"\n=== Loading {instrument_code} ===")
    init_db_with_csv_futures_contract_prices_for_code(
        instrument_code,
        datapath,
        csv_config=databento_hourly_config,
        frequency=HOURLY_FREQ,
    )

print("\nDone. Next: run `python derive_daily_from_hourly.py` to derive daily bars.")
