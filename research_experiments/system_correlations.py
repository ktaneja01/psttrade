"""Correlation of system daily returns vs SPY and GOLD over 10yr.

Also reports rolling 1yr correlation and regime-split correlations.
"""
import os
os.environ["CAPITAL"] = "500000"

import numpy as np
import pandas as pd

print("Rebuilding system for correlation analysis...")
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

# System daily pct returns
sys_r = pd.Series(system.accounts.portfolio().percent).astype(float) / 100.0
sys_r = sys_r.dropna()
sys_r.name = "SYSTEM"

def adj_px(code):
    s = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").squeeze()
    s = s.dropna().resample("1B").last().ffill()
    return s[s > 0]

spy_r  = adj_px("SP500").pct_change().dropna().rename("SPY")
gold_r = adj_px("GOLD").pct_change().dropna().rename("GOLD")

df = pd.concat([sys_r, spy_r, gold_r], axis=1).dropna()
print(f"\nCommon data points: {len(df)} ({df.index.min().date()} → {df.index.max().date()})")

print("\n" + "=" * 50)
print("Daily return correlations (10-year full sample)")
print("=" * 50)
print(df.corr().round(3).to_string())

# Weekly (less autocorrelation noise)
df_w = df.resample("W").sum()
print("\n" + "=" * 50)
print("Weekly return correlations")
print("=" * 50)
print(df_w.corr().round(3).to_string())

# Monthly
df_m = df.resample("M").sum()
print("\n" + "=" * 50)
print("Monthly return correlations")
print("=" * 50)
print(df_m.corr().round(3).to_string())

# Sub-period
regimes = [
    ("2016-2019 QE chop",       "2016-01-01", "2019-12-31"),
    ("2019-2022 Covid/inflation", "2020-01-01", "2022-12-31"),
    ("2022-2026 Hikes",          "2023-01-01", "2026-04-30"),
]
print("\n" + "=" * 50)
print("Sub-period daily correlations (SYSTEM vs SPY / GOLD)")
print("=" * 50)
print(f"{'Period':<28} {'SYS-SPY':>10} {'SYS-GOLD':>10} {'SPY-GOLD':>10}")
for label, start, end in regimes:
    sub = df[(df.index >= start) & (df.index <= end)]
    c = sub.corr()
    print(f"{label:<28} {c.loc['SYSTEM','SPY']:>+10.3f} {c.loc['SYSTEM','GOLD']:>+10.3f} "
          f"{c.loc['SPY','GOLD']:>+10.3f}")

# Rolling 1-year
roll_sys_spy  = df["SYSTEM"].rolling(252).corr(df["SPY"])
roll_sys_gold = df["SYSTEM"].rolling(252).corr(df["GOLD"])
print("\n" + "=" * 50)
print("Rolling 1-year correlations (percentiles)")
print("=" * 50)
print(f"{'Percentile':<12} {'SYS-SPY':>10} {'SYS-GOLD':>10}")
for p in [5, 25, 50, 75, 95]:
    print(f"{p:>5}%     {np.nanpercentile(roll_sys_spy,p):>+10.3f} {np.nanpercentile(roll_sys_gold,p):>+10.3f}")

# Plot
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(13, 5))
roll_sys_spy.plot(ax=ax, label="SYSTEM vs SPY", linewidth=1.3)
roll_sys_gold.plot(ax=ax, label="SYSTEM vs GOLD", linewidth=1.3)
ax.axhline(0, color="gray", linestyle="--", alpha=0.4)
ax.legend()
ax.set_title("Rolling 1-year daily return correlation — system vs passive benchmarks")
ax.set_ylabel("Correlation")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig("/tmp/system_corr_rolling.png", dpi=120)
print("\nRolling corr plot saved to /tmp/system_corr_rolling.png")
