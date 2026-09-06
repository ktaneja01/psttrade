"""Estimate margin requirements and capital-at-risk for the $500K system."""
import os
os.environ["CAPITAL"] = "500000"

import numpy as np
import pandas as pd

print("Rebuilding system for position extraction...")
exec(open("signals.py").read().split("# Build system with dynamic optimisation")[0])
from systems.basesystem import System
from systems.provided.dynamic_small_system_optimise.optimised_positions_stage import (
    optimisedPositions,
)
from systems.provided.dynamic_small_system_optimise.accounts_stage import (
    accountForOptimisedStage,
)
system = System(
    [accountForOptimisedStage(), optimisedPositions(), Portfolios(), PositionSizing(),
     RawData(), ForecastCombine(), volAttenForecastScaleCap(), Rules()],
    parquetFuturesSimData(), config,
)

CAPITAL = 500_000

# Load instrument config (pointsize + currency)
inst_cfg = pd.read_csv("/Users/kunal.taneja/pysystemtrade/data/futures/csvconfig/instrumentconfig.csv").set_index("Instrument")

# Typical SPAN-style initial margin as % of contract notional. These are
# rough round numbers based on CME/Eurex/ICE 2025 levels. Used only for
# approximate capital planning — real broker margin may vary ±30%.
MARGIN_PCT = {
    "Bond":   0.04,    # bond futures — low margin
    "STIR":   0.01,    # short rates — very low
    "Equity": 0.10,    # equity indices
    "FX":     0.04,    # currency futures
    "Metals": 0.09,
    "OilGas": 0.12,    # energy — volatile
    "Ags":    0.08,
    "Vol":    0.25,    # VIX futures — highest margin
    "Other":  0.10,
}

rows = []
total_notional = 0
total_margin = 0
for inst in config.instruments:
    try:
        pos_ts = system.accounts.get_buffered_position(inst)
        pos = float(pos_ts.dropna().iloc[-1])
    except Exception:
        pos = 0.0
    if abs(pos) < 0.5:
        continue
    pointsize = float(inst_cfg.loc[inst, "Pointsize"])
    asset_class = inst_cfg.loc[inst, "AssetClass"]
    currency = inst_cfg.loc[inst, "Currency"]
    # Latest price
    px = system.rawdata.daily_denominator_price(inst).dropna().iloc[-1]
    # FX to USD (simple: assume 1.0; we only approximate)
    fx_rate = {"USD": 1.0, "EUR": 1.07, "GBP": 1.25, "JPY": 0.0067,
               "CHF": 1.13, "AUD": 0.65, "CAD": 0.72, "SGD": 0.74,
               "MXN": 0.051, "BRL": 0.20, "KRW": 0.00072, "HKD": 0.128,
               "CNY": 0.14, "SEK": 0.094, "NOK": 0.093, "NZD": 0.59}.get(currency, 1.0)
    notional_usd = abs(pos) * px * pointsize * fx_rate
    margin_usd = notional_usd * MARGIN_PCT.get(asset_class, 0.10)
    total_notional += notional_usd
    total_margin += margin_usd
    rows.append({
        "inst": inst, "pos": pos, "px": px, "class": asset_class,
        "notional_usd": notional_usd, "margin_usd": margin_usd,
    })

df = pd.DataFrame(rows).sort_values("notional_usd", ascending=False)
print(f"\n{'Inst':<12} {'Pos':>6} {'Price':>10} {'Class':<10} {'Notional $':>13} {'Margin $':>11}")
print("-" * 75)
for _, r in df.iterrows():
    print(f"{r['inst']:<12} {r['pos']:>+6.0f} {r['px']:>10.2f} {r['class']:<10} "
          f"{r['notional_usd']:>+13,.0f} {r['margin_usd']:>+11,.0f}")

print(f"\n{'TOTALS':<12} {'':<16} {'':<10} {total_notional:>+13,.0f} {total_margin:>+11,.0f}")
print(f"\nLeverage (gross notional / capital):   {total_notional/CAPITAL:.2f}x")
print(f"Margin as % of capital:                {total_margin/CAPITAL*100:.1f}%")

# Capital-at-risk analysis
from scipy.stats import skew as scipy_skew, kurtosis as scipy_kurt
r_daily = pd.Series(system.accounts.portfolio().percent).astype(float) / 100.0
r_daily = r_daily.dropna()
pnl = r_daily * CAPITAL
cum = pnl.cumsum()
dd = cum - cum.cummax()
max_dd = dd.min()

# Simulated 99th percentile drawdown via block bootstrap
np.random.seed(42)
block_len = 63  # ~3-month blocks
n_boots = 1000
r_arr = r_daily.values
sim_max_dds = np.empty(n_boots)
n_blocks = int(np.ceil(len(r_arr) / block_len))
n_src = len(r_arr) - block_len + 1
for i in range(n_boots):
    starts = np.random.randint(0, n_src, size=n_blocks)
    sample = np.concatenate([r_arr[s:s+block_len] for s in starts])[:len(r_arr)]
    c = (sample * CAPITAL).cumsum()
    sim_max_dds[i] = (c - np.maximum.accumulate(c)).min()

p99_dd = np.percentile(sim_max_dds, 1)  # 1st percentile = 99th percentile of loss
p95_dd = np.percentile(sim_max_dds, 5)

print(f"\n{'=' * 60}")
print(f"Capital-at-risk — drawdown tail analysis")
print(f"{'=' * 60}")
print(f"Historical max DD:                     ${max_dd:>+11,.0f} "
      f"({max_dd/CAPITAL*100:.1f}% of capital)")
print(f"Bootstrap 95th-percentile DD:          ${p95_dd:>+11,.0f} "
      f"({p95_dd/CAPITAL*100:.1f}% of capital)")
print(f"Bootstrap 99th-percentile DD:          ${p99_dd:>+11,.0f} "
      f"({p99_dd/CAPITAL*100:.1f}% of capital)")

# Summary
print(f"\n{'=' * 60}")
print(f"Capital requirement scenarios")
print(f"{'=' * 60}")
minimum = total_margin
conservative = total_margin + abs(p99_dd)
practical = total_margin * 2 + abs(p99_dd)
print(f"MINIMUM (just margin, no DD buffer):         ${minimum:>10,.0f}")
print(f"CONSERVATIVE (margin + 99th %ile DD):        ${conservative:>10,.0f}")
print(f"PRACTICAL (2x margin + 99th %ile DD):        ${practical:>10,.0f}")
print(f"\nNote: margin figures are SPAN-approximate; real broker requirements")
print(f"may differ ±30% based on risk models and vol regime.")
