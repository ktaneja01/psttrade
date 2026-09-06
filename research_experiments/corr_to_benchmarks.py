"""Compute correlation of system returns to GOLD and SP500 (SPY equivalent)."""
import os
os.environ.setdefault("CAPITAL", "1000000")

import numpy as np
import pandas as pd

print("Building system...")
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
     myFuturesRawData(), ForecastCombine(), volAttenForecastScaleCap(), Rules()],
    parquetFuturesSimData(), config,
)

# System daily $ P&L
p = system.accounts.optimised_portfolio()
sys_pnl = p.as_ts.dropna()
sys_ret = sys_pnl / int(os.environ["CAPITAL"])  # convert to daily % return

# Benchmark daily returns from adjusted prices
def daily_ret(code):
    s = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").squeeze()
    s = s.dropna().resample("1B").last().ffill()
    s = s[s > 0]
    return s.pct_change().dropna()

gold = daily_ret("GOLD").rename("GOLD")
spy  = daily_ret("SP500").rename("SP500")  # SP500 futures ~ SPY

# Align
df = pd.concat([sys_ret.rename("SYSTEM"), gold, spy], axis=1).dropna()
print(f"\nAligned window: {df.index.min().date()} → {df.index.max().date()}  ({len(df)} days)")

# Full-sample correlation
print("\n=== Full-sample daily-return correlation ===")
corr = df.corr()
print(corr.round(3).to_string())

# Per-year / OOS breakout
print("\n=== Correlation by period ===")
for label, start, end in [
    ("Full 2016-2026", "2016-01-01", "2026-04-22"),
    ("Pre-OOS 2016-2023", "2016-01-01", "2023-12-31"),
    ("OOS 2024-2026", "2024-01-01", "2026-04-22"),
    ("2024", "2024-01-01", "2024-12-31"),
    ("2025", "2025-01-01", "2025-12-31"),
    ("2026 YTD", "2026-01-01", "2026-04-22"),
]:
    sub = df[(df.index >= start) & (df.index <= end)]
    if len(sub) < 30:
        continue
    c_gold = sub["SYSTEM"].corr(sub["GOLD"])
    c_spy  = sub["SYSTEM"].corr(sub["SP500"])
    print(f"  {label:<22} n={len(sub):>4}  GOLD={c_gold:+.3f}  SP500={c_spy:+.3f}")

# Monthly correlation (lower frequency, less noisy)
print("\n=== Monthly-return correlation (resampled) ===")
mdf = df.resample("M").sum()
mcorr = mdf.corr()
print(mcorr.round(3).to_string())

# Rolling 60-day correlation snapshots
print("\n=== Rolling 60-day correlation: most recent 5 snapshots ===")
roll_gold = df["SYSTEM"].rolling(60).corr(df["GOLD"])
roll_spy  = df["SYSTEM"].rolling(60).corr(df["SP500"])
tail = pd.concat([roll_gold.rename("corr_GOLD"), roll_spy.rename("corr_SP500")], axis=1).dropna().tail(30)
# Sample quarterly
print(f"{'Date':<12} {'GOLD':>8} {'SP500':>8}")
for ts, row in tail.iloc[::6].iterrows():
    print(f"  {str(ts.date()):<12} {row['corr_GOLD']:>+8.3f} {row['corr_SP500']:>+8.3f}")

# Beta to SP500 (simplest regression)
from numpy import polyfit
for bench_name in ["GOLD", "SP500"]:
    beta, alpha = polyfit(df[bench_name], df["SYSTEM"], 1)
    ann_alpha = alpha * 252 * 100
    print(f"\n{bench_name}: beta={beta:+.3f}  annualized alpha={ann_alpha:+.2f}%")
