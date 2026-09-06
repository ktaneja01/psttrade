"""Two-sleeve portfolio: 50% risk long-only SPY + 50% risk trend/carry system.
$500K capital, 20% combined vol target (uncorrelated-assumed).

Sleeve-level targets under uncorrelated assumption:
  SPY   sleeve: sqrt(0.50) × 20% = 14.14% vol target
  SYS   sleeve: sqrt(0.50) × 20% = 14.14% vol target
Sum of two sleeves (uncorrelated) has vol = 20%.
"""
import os
os.environ["CAPITAL"] = "500000"

import numpy as np
import pandas as pd

print("Rebuilding system for sleeve aggregation...")
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
COMBINED_VOL_TARGET = 0.20
W_SPY, W_SYS = 0.50, 0.50

SPY_TARGET = np.sqrt(W_SPY) * COMBINED_VOL_TARGET  # 14.14%
SYS_TARGET = np.sqrt(W_SYS) * COMBINED_VOL_TARGET  # 14.14%


def adj_px(code):
    s = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").squeeze()
    s = s.dropna().resample("1B").last().ffill()
    return s[s > 0]


def vol_targeted_long_pnl(code, target_vol, capital, span=30):
    px = adj_px(code)
    r = px.pct_change().dropna()
    realized = r.ewm(span=span, min_periods=10).std() * np.sqrt(252)
    scaler = (target_vol / realized).shift(1).clip(upper=5.0)
    return (capital * scaler * r).dropna()


print("\n" + "=" * 80)
print("TWO-SLEEVE PORTFOLIO — $500K, 20% combined vol target")
print("=" * 80)
print(f"  SPY long-only:   {W_SPY*100:.0f}% risk → target vol {SPY_TARGET*100:.2f}%")
print(f"  Trend/Carry:     {W_SYS*100:.0f}% risk → target vol {SYS_TARGET*100:.2f}%")

spy_pnl = vol_targeted_long_pnl("SP500", SPY_TARGET, CAPITAL)

sys_r = pd.Series(system.accounts.portfolio().percent).astype(float) / 100.0
sys_r = sys_r.dropna()
sys_realized = sys_r.ewm(span=30, min_periods=20).std() * np.sqrt(252)
sys_scaler = (SYS_TARGET / sys_realized).shift(1).clip(upper=5.0)
sys_pnl = (CAPITAL * sys_scaler * sys_r).dropna()

combined = pd.concat([spy_pnl.rename("spy"), sys_pnl.rename("sys")], axis=1).dropna()
combined["total"] = combined.sum(axis=1)


def stats_of(s, name):
    r = s.dropna()
    ann_mean = r.mean() * 252
    ann_std = r.std() * np.sqrt(252)
    sharpe = ann_mean / ann_std if ann_std > 0 else 0
    cum = r.cumsum()
    dd = cum - cum.cummax()
    max_dd = dd.min()
    avg_dd = dd[dd < 0].mean() if (dd < 0).any() else 0.0
    skew = r.skew()
    hit = (r > 0).mean()
    return {"name": name, "sharpe": sharpe, "ann_mean": ann_mean, "ann_std": ann_std,
            "skew": skew, "max_dd": max_dd, "avg_dd": avg_dd, "hit": hit}


rows = [stats_of(combined["spy"], "SPY (50% risk)"),
        stats_of(combined["sys"], "Trend/Carry (50% risk)"),
        stats_of(combined["total"], "COMBINED")]

print("\n" + "=" * 115)
print(f"{'Sleeve':<25s} {'Sharpe':>8s} {'Ann Mean $':>12s} {'Ann Std $':>12s} "
      f"{'RealVol':>8s} {'Skew':>7s} {'Max DD $':>12s} {'Avg DD $':>12s} {'Hit':>6s}")
print("-" * 115)
for r in rows:
    print(f"{r['name']:<25s} {r['sharpe']:>+8.3f} {r['ann_mean']:>+12.0f} {r['ann_std']:>+12.0f} "
          f"{r['ann_std']/CAPITAL*100:>7.1f}% {r['skew']:>+7.2f} {r['max_dd']:>+12.0f} {r['avg_dd']:>+12.0f} "
          f"{r['hit']*100:>5.1f}%")

print("\nSleeve correlations (daily):")
print(combined[["spy","sys"]].corr().round(3).to_string())

# OOS slice 2024-2026
oos = combined[combined.index >= "2024-01-01"]
print("\n" + "=" * 80)
print("OOS 2024-2026 slice")
print("=" * 80)
print(f"{'Sleeve':<25s} {'Sharpe':>8s} {'Ann Mean $':>12s} {'Ann Std $':>12s} {'Total $':>12s}")
print("-" * 80)
for col, name in [("spy","SPY"), ("sys","Trend/Carry"), ("total","COMBINED")]:
    r = oos[col].dropna()
    ann_mean = r.mean() * 252
    ann_std = r.std() * np.sqrt(252)
    sr = ann_mean / ann_std if ann_std > 0 else 0
    total = r.sum()
    print(f"{name:<25s} {sr:>+8.3f} {ann_mean:>+12.0f} {ann_std:>+12.0f} {total:>+12.0f}")

# Save equity curve
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(13, 7))
for col, color, lw in [("spy","#4a90e2",1.0), ("sys","#e67e22",1.0), ("total","#2ca02c",1.5)]:
    combined[col].cumsum().plot(ax=ax, label=col, linewidth=lw, color=color)
ax.axvspan(pd.Timestamp("2024-01-01"), combined.index[-1], alpha=0.08, color="gray", label="OOS")
ax.legend(loc="upper left")
ax.set_title(f"Two-sleeve: 50% SPY + 50% Trend/Carry  |  "
             f"Combined SR {rows[-1]['sharpe']:+.3f}  |  "
             f"RealVol {rows[-1]['ann_std']/CAPITAL*100:.1f}%")
ax.set_ylabel("Cumulative P&L ($)")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig("/tmp/two_sleeve_equity.png", dpi=120)
print("\nEquity curve saved to /tmp/two_sleeve_equity.png")
