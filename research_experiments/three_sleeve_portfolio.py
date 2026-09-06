"""Three-sleeve portfolio on $500K at 20% vol target:
  50% risk  — long-only SPY (SP500 futures), vol-targeted
  20% risk  — long-only GOLD, vol-targeted
  30% risk  — our full trend/carry system (current signals.py config)

Risk weights translate to sleeve-level vol targets under the uncorrelated assumption:
  target_i = sqrt(w_i) × 20%       →  SPY=14.14%, GOLD=8.94%, SYS=10.95%
Sum of sleeves then has variance 0.5*400 + 0.2*400 + 0.3*400 = 400 → 20% combined.
"""
import os
os.environ["CAPITAL"] = "500000"

import numpy as np
import pandas as pd

# Build the signals.py system (reuses full config)
exec(open("signals.py").read().split("# Build system with dynamic optimisation")[0])

from systems.basesystem import System
from systems.provided.dynamic_small_system_optimise.optimised_positions_stage import (
    optimisedPositions,
)
from systems.provided.dynamic_small_system_optimise.accounts_stage import (
    accountForOptimisedStage,
)

system = System(
    [
        accountForOptimisedStage(),
        optimisedPositions(),
        Portfolios(),
        PositionSizing(),
        RawData(),
        ForecastCombine(),
        volAttenForecastScaleCap(),
        Rules(),
    ],
    parquetFuturesSimData(),
    config,
)

CAPITAL = 500_000
COMBINED_VOL_TARGET = 0.20
W_SPY, W_GOLD, W_SYS = 0.50, 0.20, 0.30

SPY_TARGET  = np.sqrt(W_SPY)  * COMBINED_VOL_TARGET  # 14.14%
GOLD_TARGET = np.sqrt(W_GOLD) * COMBINED_VOL_TARGET  # 8.94%
SYS_TARGET  = np.sqrt(W_SYS)  * COMBINED_VOL_TARGET  # 10.95%


def adjusted_px(code):
    s = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").squeeze()
    s = s.dropna().resample("1B").last().ffill()
    return s[s > 0]


def vol_targeted_long_pnl(code, target_vol, capital, span=30):
    """Daily dollar P&L of a vol-targeted constant-long position."""
    px = adjusted_px(code)
    r = px.pct_change().dropna()
    realized = r.ewm(span=span, min_periods=10).std() * np.sqrt(252)
    scaler = (target_vol / realized).shift(1).clip(upper=5.0)
    pnl = capital * scaler * r
    return pnl.dropna()


print("\n" + "=" * 80)
print("Three-sleeve portfolio — $500K capital, 20% combined vol target")
print("=" * 80)
print(f"  SPY long-only:   {W_SPY*100:.0f}% risk  →  target vol {SPY_TARGET*100:.2f}%")
print(f"  GOLD long-only:  {W_GOLD*100:.0f}% risk  →  target vol {GOLD_TARGET*100:.2f}%")
print(f"  Trend/carry:     {W_SYS*100:.0f}% risk  →  target vol {SYS_TARGET*100:.2f}%")

spy_pnl  = vol_targeted_long_pnl("SP500", SPY_TARGET, CAPITAL)
gold_pnl = vol_targeted_long_pnl("GOLD",  GOLD_TARGET, CAPITAL)

pnl_pct = system.accounts.portfolio().percent
pnl_pct = pd.Series(pnl_pct).astype(float) / 100.0
pnl_pct = pnl_pct.dropna()
realized_sys = pnl_pct.ewm(span=30, min_periods=20).std() * np.sqrt(252)
scaler_sys = (SYS_TARGET / realized_sys).shift(1).clip(upper=5.0)
sys_pnl = (CAPITAL * scaler_sys * pnl_pct).dropna()

combined = pd.concat([spy_pnl.rename("spy"),
                      gold_pnl.rename("gold"),
                      sys_pnl.rename("sys")], axis=1).dropna()
combined["total"] = combined.sum(axis=1)


def stats_of(s, name):
    r = s.dropna()
    ann_mean = r.mean() * 252
    ann_std  = r.std() * np.sqrt(252)
    sharpe   = ann_mean / ann_std if ann_std > 0 else 0
    cum      = r.cumsum()
    dd       = (cum - cum.cummax())
    max_dd   = dd.min()
    avg_dd   = dd[dd < 0].mean() if (dd < 0).any() else 0.0
    skew     = r.skew()
    hit      = (r > 0).mean()
    return {"name": name, "sharpe": float(sharpe), "ann_mean": float(ann_mean),
            "ann_std": float(ann_std), "skew": float(skew),
            "max_dd": float(max_dd), "avg_dd": float(avg_dd), "hit": float(hit)}


rows = [stats_of(combined["spy"],   "SPY (50% risk)"),
        stats_of(combined["gold"],  "GOLD (20% risk)"),
        stats_of(combined["sys"],   "Trend/Carry (30% risk)"),
        stats_of(combined["total"], "COMBINED")]

print("\n" + "=" * 115)
print(f"{'Sleeve':<25s} {'Sharpe':>8s} {'Ann Mean $':>12s} {'Ann Std $':>12s} "
      f"{'RealVol':>8s} {'Skew':>7s} {'Max DD $':>12s} {'Avg DD $':>12s} {'Hit':>6s}")
print("-" * 115)
for r in rows:
    print(f"{r['name']:<25s} {r['sharpe']:>+8.3f} {r['ann_mean']:>+12.0f} {r['ann_std']:>+12.0f} "
          f"{r['ann_std']/CAPITAL*100:>7.1f}% {r['skew']:>+7.2f} {r['max_dd']:>+12.0f} {r['avg_dd']:>+12.0f} "
          f"{r['hit']*100:>5.1f}%")

print("\nSleeve return correlations (daily):")
print(combined[["spy","gold","sys"]].corr().round(3).to_string())

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(13, 7))
for col in ["spy","gold","sys","total"]:
    combined[col].cumsum().plot(ax=ax, label=col, linewidth=1.4 if col=="total" else 0.9)
ax.legend()
ax.set_title(f"Three-sleeve portfolio equity curves ($500K, 20% target)\n"
             f"Combined Sharpe={rows[-1]['sharpe']:+.3f}, "
             f"Realised vol={rows[-1]['ann_std']/CAPITAL*100:.1f}%")
ax.set_ylabel("Cumulative P&L ($)")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig("/tmp/three_sleeve_equity.png", dpi=120)
print("\nEquity curve saved to /tmp/three_sleeve_equity.png")
