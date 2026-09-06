"""Clean OOS 2024-2026 test: build system on full 2016-2026 data so IDM/correlations
are properly calibrated, then slice the P&L output to 2024+ for reporting."""
import os
os.environ.setdefault("CAPITAL", "1000000")

import numpy as np
import pandas as pd
from scipy.stats import skew as scipy_skew, kurtosis as scipy_kurt

print("Rebuilding system (full 2016-2026 history for IDM / correlations)...")
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

CAPITAL = int(os.environ["CAPITAL"])
OOS_START = "2024-01-01"
r_all = pd.Series(system.accounts.portfolio().percent).astype(float) / 100.0
r_all = r_all.dropna()
r_oos = r_all[r_all.index >= OOS_START]
dollar_oos = r_oos * CAPITAL

print(f"\nOOS window: {r_oos.index.min().date()} → {r_oos.index.max().date()} "
      f"({len(r_oos)} trading days)")

def stats(r):
    n = len(r)
    ann_mean = r.mean() * 252
    ann_std  = r.std() * np.sqrt(252)
    sharpe   = ann_mean / ann_std if ann_std > 0 else 0
    ds = r[r < 0].std() * np.sqrt(252)
    sortino  = ann_mean / ds if ds > 0 else 0
    cum = r.cumsum()
    dd = cum - cum.cummax()
    return {
        "n": n, "sharpe": sharpe, "sortino": sortino,
        "ann_mean_pct": ann_mean * 100, "ann_std_pct": ann_std * 100,
        "skew": float(scipy_skew(r)), "ex_kurt": float(scipy_kurt(r, fisher=True)),
        "hit": (r > 0).mean(), "max_dd_pct": dd.min() * 100,
        "worst_day_pct": r.min() * 100, "best_day_pct": r.max() * 100,
    }

oos_stats = stats(r_oos)
full_stats = stats(r_all)

print("\n" + "=" * 80)
print("OOS 2024-2026 (system built on full 2016-2026 history)")
print("=" * 80)
labels = ["Sharpe", "Sortino", "Ann mean %", "Ann std %", "RealVol %",
          "Skew", "ExKurt", "Hit %", "MaxDD %", "WorstDay %", "BestDay %"]
oos_vals = [oos_stats['sharpe'], oos_stats['sortino'],
            oos_stats['ann_mean_pct'], oos_stats['ann_std_pct'], oos_stats['ann_std_pct'],
            oos_stats['skew'], oos_stats['ex_kurt'], oos_stats['hit']*100,
            oos_stats['max_dd_pct'], oos_stats['worst_day_pct'], oos_stats['best_day_pct']]
full_vals = [full_stats['sharpe'], full_stats['sortino'],
             full_stats['ann_mean_pct'], full_stats['ann_std_pct'], full_stats['ann_std_pct'],
             full_stats['skew'], full_stats['ex_kurt'], full_stats['hit']*100,
             full_stats['max_dd_pct'], full_stats['worst_day_pct'], full_stats['best_day_pct']]

print(f"{'Metric':<16} {'OOS 2024-26':>14} {'Full 2016-26':>14}")
print("-" * 50)
for l, o, f in zip(labels, oos_vals, full_vals):
    print(f"{l:<16} {o:>14.3f} {f:>14.3f}")

# Annualised $
print(f"\nAnn mean $   OOS: {oos_stats['ann_mean_pct']/100*CAPITAL:>+9.0f}  |  "
      f"Full: {full_stats['ann_mean_pct']/100*CAPITAL:>+9.0f}")
print(f"Ann std $    OOS: {oos_stats['ann_std_pct']/100*CAPITAL:>+9.0f}  |  "
      f"Full: {full_stats['ann_std_pct']/100*CAPITAL:>+9.0f}")

# Per-instrument OOS P&L
print("\n" + "=" * 80)
print("Per-asset-class OOS 2024-2026 $ P&L and Sharpe")
print("=" * 80)
asset_classes = {}
for cls, insts in _raw_asset_classes.items():
    active = [i for i in insts if i not in bad_markets and i in config.instruments]
    if active:
        asset_classes[cls] = active

print(f"{'Class':<18} {'#inst':>5} {'MeanSR':>8} {'MedSR':>8} {'Ann $':>10} {'+ve':>5}")
print("-" * 58)
for cls, insts in asset_classes.items():
    sharpes = []
    ann_dollars = 0
    positive = 0
    for inst in insts:
        try:
            p = system.accounts.pandl_for_optimised_instrument(inst)
            p_oos = p[p.index >= OOS_START].dropna()
            if len(p_oos) < 50 or p_oos.std() == 0:
                continue
            sr = float(p_oos.mean() / p_oos.std() * np.sqrt(252))
            if np.isnan(sr):
                continue
            sharpes.append(sr)
            ann_dollars += float(p_oos.mean() * 252)
            if sr > 0:
                positive += 1
        except Exception:
            continue
    if sharpes:
        print(f"{cls:<18} {len(sharpes):>5d} {np.mean(sharpes):>+8.3f} "
              f"{np.median(sharpes):>+8.3f} {ann_dollars:>+10.0f} {positive:>2d}/{len(sharpes):<2d}")
