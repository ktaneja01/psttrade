from sysinit.futures.rollcalendars_from_db_prices_to_csv import build_and_write_roll_calendar

output_datapath = "/tmp/roll_calendars"
instruments = [
    # Equity
    "SP500", "NASDAQ", "RUSSELL", "DOW", "NIKKEI",
    # Rates
    "SOFR", "SOFR1", "FED", "US2", "US3", "US5", "US10", "US10U", "US20", "US30",
    # FX
    "EUR", "JPY", "GBP", "AUD", "NZD", "MXP", "CHF", "CAD",
    "BRE", "ZAR", "PLN", "INR", "CNH-CME", "EURCHF", "GBPEUR",
    # Energy
    "CRUDE_W", "BRENT_W", "GAS_US", "GASOILINE", "HEATOIL",
    "GAS-LAST", "GAS-PEN",
    # Metals
    "GOLD", "SILVER", "COPPER", "PLAT", "PALLAD", "ALUMINIUM", "STEEL",
    # Grains
    "WHEAT", "REDWHEAT", "SOYBEAN", "SOYMEAL", "SOYOIL", "CORN", "OATIES", "RICE",
    # Livestock / Dairy
    "LEANHOG", "LIVECOW", "FEEDCOW", "MILK", "CHEESE", "BUTTER",
    # Crypto
    "BITCOIN", "ETHEREUM",
    # Lumber
    "LUMBER-new",
]

succeeded, failed = [], []

for instrument_code in instruments:
    print(f"\n=== Building roll calendar for {instrument_code} ===")
    try:
        build_and_write_roll_calendar(
            instrument_code,
            output_datapath=output_datapath,
            check_before_writing=False,
        )
        succeeded.append(instrument_code)
    except Exception as e:
        print(f"FAILED {instrument_code}: {type(e).__name__}: {e}")
        failed.append(instrument_code)

print(f"\n=== Summary ===")
print(f"Succeeded ({len(succeeded)}): {succeeded}")
print(f"Failed ({len(failed)}): {failed}")
