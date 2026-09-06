from syscore.dateutils import HOURLY_FREQ
from sysdata.csv.csv_futures_contract_prices import ConfigCsvFuturesPrices
from sysinit.futures.contract_prices_from_csv_to_db import (
    init_db_with_csv_futures_contract_prices_for_code,
)

bcutils_hourly_config = ConfigCsvFuturesPrices(
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

datapath = "/tmp/barchart_data"
instruments = [
    # More equity indices
    "CAC", "FTSE100", "RUSSELL", "DOW",
    # More FX
    "CHF", "DX",
    # More energy
    "GASOIL", "GASOILINE",
    # More metals
    "SILVER", "PLAT", "PALLAD",
    # Vol
    "V2X",
    # More softs
    "COCOA",
    # More ags
    "RICE", "OATIES", "OJ",
    # More bonds
    "US20",
    # Crypto
    "BITCOIN", "ETHEREUM",
]

for instrument_code in instruments:
    print(f"\n=== Loading {instrument_code} ===")
    init_db_with_csv_futures_contract_prices_for_code(
        instrument_code,
        datapath,
        csv_config=bcutils_hourly_config,
        frequency=HOURLY_FREQ,
    )

print("\nDone. Next: run `python sysinit/futures/create_hourly_and_daily.py` to derive daily bars.")
