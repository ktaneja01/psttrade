"""Estimate margin requirements for the $1M system."""
import os
os.environ["CAPITAL"] = "1000000"

import numpy as np
import pandas as pd

print("Building system at $1M...")
exec(open("signals.py").read().split("# Build system with dynamic optimisation")[0])
from systems.basesystem import System
from systems.provided.dynamic_small_system_optimise.optimised_positions_stage import optimisedPositions
from systems.provided.dynamic_small_system_optimise.accounts_stage import accountForOptimisedStage
system = System(
    [accountForOptimisedStage(), optimisedPositions(), Portfolios(), PositionSizing(),
     myFuturesRawData(), ForecastCombine(), volAttenForecastScaleCap(), Rules()],
    parquetFuturesSimData(), config,
)

CAPITAL = 1_000_000
# Typical exchange initial margin rates (% of notional contract value)
# Source: CME / ICE / Eurex public margin tables, approximate Apr 2026
DEFAULT_MARGIN_RATE = 0.10
INSTRUMENT_MARGIN_RATES = {
    # Bonds (low margin since low vol)
    "US10": 0.025, "US30": 0.04, "BUND": 0.03, "GILT": 0.03, "BTP": 0.04,
    # Equity indices
    "SP500": 0.07, "RUSSELL": 0.10, "NIKKEI": 0.08, "EUROSTX": 0.08, "FTSE100": 0.07,
    "AEX": 0.08, "HANG": 0.10, "SMI": 0.07, "TECDAX": 0.10,
    # Vol
    "VIX": 0.25, "V2X": 0.25,
    # Currencies (typically 2-4%)
    "EUR": 0.025, "JPY": 0.025, "GBP": 0.025, "AUD": 0.03, "NZD": 0.03,
    "CHF": 0.03, "PLN": 0.05, "EURCAD": 0.025, "NOK": 0.03, "SEK": 0.03,
    # Energy (high margin)
    "CRUDE_W": 0.10, "GASOILINE": 0.10, "HEATOIL": 0.10, "GAS-LAST": 0.15, "GASOIL": 0.10,
    "EUA": 0.10,
    # Metals
    "GOLD": 0.06, "SILVER": 0.10, "COPPER": 0.10, "PLAT": 0.08, "PALLAD": 0.15,
    "ALUMINIUM_LME": 0.08, "ZINC_LME": 0.10,
    # Grains
    "REDWHEAT": 0.07, "WHEAT": 0.07, "CORN": 0.07, "SOYBEAN": 0.07, "SOYMEAL": 0.08, "SOYOIL": 0.08,
    # Livestock
    "LIVECOW": 0.08, "FEEDCOW": 0.08, "LEANHOG": 0.10, "RICE": 0.07,
    # Softs
    "COCOA": 0.10, "COFFEE": 0.10, "OJ": 0.10, "ROBUSTA": 0.10,
    # Crypto (very high margin)
    "BITCOIN": 0.45, "ETHEREUM": 0.50,
    # Other
    "GBPJPY": 0.04, "MXP": 0.04, "ZAR": 0.05, "BRE": 0.05,
}

# Get positions for each instrument over time
print("\nFetching daily positions for each instrument...")
positions_dict = {}
for inst in config.instruments:
    try:
        pos = system.accounts.get_optimised_position(inst)
        positions_dict[inst] = pos
    except Exception as e:
        print(f"  {inst}: ERROR {e}")

# Build aligned positions DataFrame
positions_df = pd.DataFrame(positions_dict).fillna(0)
print(f"  Positions shape: {positions_df.shape}")

# For each day, compute |position| × contract_notional × margin_rate
print("\nComputing margin requirement per day...")
margin_per_inst = {}
for inst in config.instruments:
    if inst not in positions_dict:
        continue
    try:
        # Get daily prices and contract multiplier
        adj_price = system.rawdata.get_daily_prices(inst)
        # Match dates to positions
        aligned_price = adj_price.reindex(positions_df.index, method="ffill")
        # Contract multiplier (pointsize × fx)
        multiplier = system.data.get_value_of_block_price_move(inst)
        fx_rate = system.data.get_fx_for_instrument(inst, "USD") if hasattr(system.data, "get_fx_for_instrument") else 1.0
        # Use last fx rate as approximation
        fx_val = fx_rate.iloc[-1] if hasattr(fx_rate, "iloc") else 1.0
        # Notional per contract = price × multiplier × fx
        notional_per_contract = aligned_price * multiplier * fx_val
        # Position margin = |position| × notional × margin_rate
        margin_rate = INSTRUMENT_MARGIN_RATES.get(inst, DEFAULT_MARGIN_RATE)
        margin_per_inst[inst] = (positions_df[inst].abs() * notional_per_contract * margin_rate).fillna(0)
    except Exception as e:
        print(f"  {inst}: skipped ({e})")
        continue

margin_df = pd.DataFrame(margin_per_inst).fillna(0)
total_margin = margin_df.sum(axis=1)

# Stats
print(f"\nMargin window: {total_margin.index.min().date()} → {total_margin.index.max().date()}")
print(f"Total daily margin requirement (USD):")
print(f"  Mean:   ${total_margin.mean():>14,.0f}  ({total_margin.mean()/CAPITAL*100:>5.1f}% of capital)")
print(f"  Median: ${total_margin.median():>14,.0f}  ({total_margin.median()/CAPITAL*100:>5.1f}% of capital)")
print(f"  P95:    ${total_margin.quantile(0.95):>14,.0f}  ({total_margin.quantile(0.95)/CAPITAL*100:>5.1f}% of capital)")
print(f"  P99:    ${total_margin.quantile(0.99):>14,.0f}  ({total_margin.quantile(0.99)/CAPITAL*100:>5.1f}% of capital)")
print(f"  Max:    ${total_margin.max():>14,.0f}  ({total_margin.max()/CAPITAL*100:>5.1f}% of capital)")
print(f"  Min:    ${total_margin.min():>14,.0f}")

# OOS only
oos_margin = total_margin[total_margin.index >= "2024-01-01"]
if len(oos_margin) > 50:
    print(f"\nOOS 2024-2026 only:")
    print(f"  Mean:   ${oos_margin.mean():>14,.0f}  ({oos_margin.mean()/CAPITAL*100:>5.1f}%)")
    print(f"  P95:    ${oos_margin.quantile(0.95):>14,.0f}  ({oos_margin.quantile(0.95)/CAPITAL*100:>5.1f}%)")
    print(f"  Max:    ${oos_margin.max():>14,.0f}  ({oos_margin.max()/CAPITAL*100:>5.1f}%)")

# Top contributors to margin
print(f"\nMean margin contribution by instrument (top 15):")
mean_per_inst = margin_df.mean().sort_values(ascending=False)
total_mean = mean_per_inst.sum()
for inst, m in mean_per_inst.head(15).items():
    pct = m / total_mean * 100 if total_mean > 0 else 0
    print(f"  {inst:<14}  ${m:>10,.0f}  ({pct:>5.1f}%)")
