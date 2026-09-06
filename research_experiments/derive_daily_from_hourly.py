from syscore.dateutils import HOURLY_FREQ, DAILY_PRICE_FREQ, MIXED_FREQ
from sysproduction.data.prices import diagPrices
import pandas as pd

diag = diagPrices()
db = diag.db_futures_contract_price_data

instruments = [
    # Equity
    "SP500", "NASDAQ", "RUSSELL", "DOW", "NIKKEI", "SP400",
    # Rates
    "SOFR", "SOFR1", "FED", "US2", "US3", "US5", "US10", "US10U", "US20", "US30",
    # FX
    "EUR", "JPY", "GBP", "AUD", "NZD", "MXP", "CHF", "CAD",
    "BRE", "ZAR", "PLN", "INR", "CNH-CME", "EURCHF", "GBPEUR",
    # Energy
    "CRUDE_W", "BRENT_W", "GAS_US", "GASOILINE", "HEATOIL",
    "BRENT-LAST", "GAS-LAST", "GAS-PEN", "ETHANOL",
    # Metals
    "GOLD", "SILVER", "COPPER", "PLAT", "PALLAD", "ALUMINIUM", "STEEL",
    # Grains
    "WHEAT", "REDWHEAT", "SOYBEAN", "SOYMEAL", "SOYOIL", "CORN", "OATIES", "RICE",
    # Livestock / Dairy
    "LEANHOG", "LIVECOW", "FEEDCOW", "MILK", "CHEESE", "BUTTER",
    # Crypto
    "BITCOIN", "ETHEREUM", "BRR",
    # Lumber
    "LUMBER-new",
]


def last_bar_per_day(hourly: pd.DataFrame) -> pd.DataFrame:
    """Take last bar per date; robust to different exchange closing times."""
    if len(hourly) == 0:
        return hourly
    grouped = hourly.groupby(hourly.index.date)
    last_idx = grouped.apply(lambda g: g.index[-1])
    return hourly.loc[list(last_idx.values)]


for instrument_code in instruments:
    print(f"\n=== Processing {instrument_code} ===")
    contracts = db.get_contracts_with_price_data_for_frequency(HOURLY_FREQ)
    contracts = [c for c in contracts if c.instrument_code == instrument_code]
    print(f"Found {len(contracts)} hourly contracts")

    for contract in contracts:
        hourly = db.get_prices_at_frequency_for_contract_object(
            contract, frequency=HOURLY_FREQ
        )
        if len(hourly) == 0:
            continue

        daily = last_bar_per_day(hourly)

        if len(daily) > 0:
            db.write_prices_at_frequency_for_contract_object(
                contract, futures_price_data=daily,
                ignore_duplication=True, frequency=DAILY_PRICE_FREQ,
            )
        db.write_prices_at_frequency_for_contract_object(
            contract, futures_price_data=hourly,
            ignore_duplication=True, frequency=MIXED_FREQ,
        )

print("\nDone.")
