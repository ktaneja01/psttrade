from sysinit.futures.multipleprices_from_db_prices_and_csv_calendars_to_db import (
    process_multiple_prices_single_instrument,
)

instruments = [
    # Equity (5)
    "SP500", "NASDAQ", "RUSSELL", "DOW", "NIKKEI",
    # Rates (10)
    "SOFR", "SOFR1", "FED", "US2", "US3", "US5", "US10", "US10U", "US20", "US30",
    # FX (12, excluding BRE/PLN/INR which failed calendar build)
    "EUR", "JPY", "GBP", "AUD", "NZD", "MXP", "CHF", "CAD",
    "ZAR", "CNH-CME", "EURCHF", "GBPEUR",
    # Energy (7)
    "CRUDE_W", "BRENT_W", "GAS_US", "GASOILINE", "HEATOIL", "GAS-LAST", "GAS-PEN",
    # Metals (7)
    "GOLD", "SILVER", "COPPER", "PLAT", "PALLAD", "ALUMINIUM", "STEEL",
    # Grains (5, excluding WHEAT/SOYBEAN/CORN which failed calendar build)
    "REDWHEAT", "SOYMEAL", "SOYOIL", "OATIES", "RICE",
    # Livestock / Dairy (6)
    "LEANHOG", "LIVECOW", "FEEDCOW", "MILK", "CHEESE", "BUTTER",
    # Crypto (2)
    "BITCOIN", "ETHEREUM",
    # Lumber (1)
    "LUMBER-new",
]

succeeded, failed = [], []

for instrument_code in instruments:
    print(f"\n=== {instrument_code} ===")
    try:
        process_multiple_prices_single_instrument(
            instrument_code,
            ADD_TO_DB=True,
            ADD_TO_CSV=False,
        )
        succeeded.append(instrument_code)
    except Exception as e:
        print(f"FAILED {instrument_code}: {type(e).__name__}: {e}")
        failed.append(instrument_code)

print(f"\nSucceeded ({len(succeeded)}): {succeeded}")
print(f"Failed ({len(failed)}): {failed}")
