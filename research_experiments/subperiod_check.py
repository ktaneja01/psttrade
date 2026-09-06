"""Sub-period Sharpe consistency check (Prado Tier-1 robustness test).

Splits the 10-year portfolio return series into regime-distinct windows and
reports Sharpe + tail stats in each. If Sharpe holds in all sub-periods,
DSR becomes much more convincing. If it's concentrated in one regime,
that's a red flag regardless of full-sample Sharpe.
"""
import os
os.environ["CAPITAL"] = "500000"

import numpy as np
import pandas as pd
from scipy.stats import skew as scipy_skew, kurtosis as scipy_kurt

print("Rebuilding system to extract daily portfolio returns...")
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
returns_pct = pd.Series(system.accounts.portfolio().percent).astype(float) / 100.0
returns_pct = returns_pct.dropna()
pnl_dollars = returns_pct * CAPITAL


def stats(r_pct, r_dollars, label, regime):
    r_pct = r_pct.dropna()
    r_dollars = r_dollars.dropna()
    n = len(r_pct)
    ann_mean_pct  = r_pct.mean() * 252
    ann_std_pct   = r_pct.std() * np.sqrt(252)
    ann_mean_dol  = r_dollars.mean() * 252
    ann_std_dol   = r_dollars.std() * np.sqrt(252)
    sharpe        = ann_mean_pct / ann_std_pct if ann_std_pct > 0 else 0
    # Sortino (downside-only vol)
    downside_pct  = r_pct[r_pct < 0].std() * np.sqrt(252)
    sortino       = ann_mean_pct / downside_pct if downside_pct > 0 else 0
    skew          = scipy_skew(r_pct)
    ex_kurt       = scipy_kurt(r_pct, fisher=True)
    hit           = (r_pct > 0).mean()
    # Drawdowns (on dollar cum)
    cum = r_dollars.cumsum()
    dd  = (cum - cum.cummax())
    max_dd = dd.min()
    worst_day = r_dollars.min()
    # Longest drawdown duration (days)
    underwater = (dd < 0).astype(int)
    if underwater.any():
        groups = (underwater.diff() != 0).cumsum()
        dur = underwater.groupby(groups).sum().max()
    else:
        dur = 0
    return {
        "label": label, "regime": regime, "n": n,
        "sharpe": sharpe, "sortino": sortino,
        "ann_mean_pct": ann_mean_pct * 100, "ann_std_pct": ann_std_pct * 100,
        "ann_mean_dol": ann_mean_dol, "ann_std_dol": ann_std_dol,
        "skew": float(skew), "ex_kurt": float(ex_kurt),
        "hit": hit, "max_dd": max_dd, "worst_day": worst_day,
        "max_dd_days": int(dur),
    }


periods = [
    ("2016-2019", "QE / low-vol chop",      "2016-01-01", "2019-12-31"),
    ("2019-2022", "Covid + initial infl.",  "2020-01-01", "2022-12-31"),
    ("2022-2026", "Hikes + normalization",  "2023-01-01", "2026-04-30"),
    ("FULL",      "10-year aggregate",      "2016-01-01", "2026-04-30"),
]

rows = []
for label, regime, start, end in periods:
    mask = (returns_pct.index >= start) & (returns_pct.index <= end)
    rows.append(stats(returns_pct[mask], pnl_dollars[mask], label, regime))

print("\n" + "=" * 140)
print("Sub-period Sharpe consistency check")
print("=" * 140)
hdr = f"{'Period':<12} {'Regime':<30} {'N':>6} {'Sharpe':>8} {'Sortino':>8} "
hdr += f"{'Ann %':>7} {'Ann $':>9} {'Std %':>7} {'Skew':>7} {'ExKurt':>7} "
hdr += f"{'Hit':>6} {'MaxDD$':>10} {'WorstDay':>10} {'DDdays':>7}"
print(hdr)
print("-" * 140)
for r in rows:
    print(f"{r['label']:<12} {r['regime']:<30} {r['n']:>6d} {r['sharpe']:>+8.3f} "
          f"{r['sortino']:>+8.3f} {r['ann_mean_pct']:>+7.2f} {r['ann_mean_dol']:>+9.0f} "
          f"{r['ann_std_pct']:>7.2f} {r['skew']:>+7.2f} {r['ex_kurt']:>+7.2f} "
          f"{r['hit']*100:>5.1f}% {r['max_dd']:>+10.0f} {r['worst_day']:>+10.0f} {r['max_dd_days']:>7d}")

print("\n" + "=" * 140)
print("Consistency diagnosis")
print("=" * 140)
subs = [r for r in rows if r['label'] != "FULL"]
sharpes = [r['sharpe'] for r in subs]
print(f"  Sub-period Sharpes:     {[round(s,3) for s in sharpes]}")
print(f"  Min sub-period Sharpe:  {min(sharpes):+.3f}")
print(f"  Max sub-period Sharpe:  {max(sharpes):+.3f}")
print(f"  Range:                  {max(sharpes) - min(sharpes):.3f}")
print(f"  All periods positive:   {'YES' if all(s > 0 for s in sharpes) else 'NO'}")

# Fraction of full-sample ann$ coming from each sub-period
full_dol = [r['ann_mean_dol'] * r['n'] for r in rows if r['label'] == 'FULL'][0]
print(f"\n  Contribution decomposition (share of total 10y $ P&L):")
for r in subs:
    share = r['ann_mean_dol'] * r['n'] / full_dol * 100
    print(f"    {r['label']}: {share:>5.1f}%")

# Regime-specific risk-adjusted
print("\n  Interpretation:")
if all(s > 0.15 for s in sharpes) and max(sharpes) - min(sharpes) < 0.30:
    print("    ✓ Sharpe is stable across regimes (all > 0.15, spread < 0.30)")
    print("    → Strategy's alpha is not concentrated in one regime.")
    print("    → DSR of 0.85 is meaningful; forward-confidence upgraded.")
elif all(s > 0 for s in sharpes):
    print("    ~ Positive in all regimes but uneven magnitude.")
    print("    → Strategy works but has clear regime dependency.")
    print("    → Watch drawdown in weaker regime; size conservatively.")
else:
    print("    ✗ At least one sub-period negative.")
    print("    → Full-sample Sharpe is carried by a favorable regime.")
    print("    → Strategy may not survive regime-change; DSR result is misleading.")
