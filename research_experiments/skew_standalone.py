"""10yr backtest stats for the 4 skew rules individually + combined."""
import os
os.environ["CAPITAL"] = "500000"

import numpy as np
import pandas as pd

print("Rebuilding system...")
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

print("\n" + "=" * 115)
print("Skew rules — 10yr backtest stats (weighted by forecast_weight × instrument_weight × IDM)")
print("=" * 115)
hdr = (f"{'Rule':<14} {'Sharpe':>8} {'Sortino':>8} {'Ann $':>8} {'Ann std':>9} "
       f"{'Mean':>8} {'Median':>8} {'Skew':>7} {'ExKurt':>7} {'HitR':>6} {'PF':>6} {'t-stat':>7}")
print(hdr)
print("-" * 115)

skew_rules = ["skewabs180", "skewabs365", "skewrv180", "skewrv365"]

all_pnl = None
for rule in skew_rules:
    try:
        p = system.accounts.pandl_for_trading_rule_weighted(rule)
        s = dict(p.stats()[0])
        r = p.as_ts
        sharpe   = float(s.get("sharpe", 0) or 0)
        sortino  = float(s.get("sortino", 0) or 0)
        ann_mean = float(s.get("ann_mean", 0) or 0)
        ann_std  = float(s.get("ann_std", 0) or 0)
        mean_d   = float(s.get("mean", 0) or 0)
        median_d = float(s.get("median", 0) or 0)
        skew     = float(s.get("skew", 0) or 0)
        # Compute excess kurtosis from the series
        ex_kurt  = float(r.kurtosis())
        hitrate  = float(s.get("hitrate", 0) or 0)
        pf       = float(s.get("profitfactor", 0) or 0)
        t_stat   = float(s.get("t_stat", 0) or 0)

        print(f"{rule:<14} {sharpe:>+8.3f} {sortino:>+8.3f} {ann_mean:>+8.0f} {ann_std:>+9.0f} "
              f"{mean_d:>+8.2f} {median_d:>+8.2f} {skew:>+7.2f} {ex_kurt:>+7.2f} "
              f"{hitrate:>6.3f} {pf:>6.3f} {t_stat:>+7.2f}")

        # Sum for combined skew
        r_series = r.dropna()
        if all_pnl is None:
            all_pnl = r_series
        else:
            all_pnl = all_pnl.add(r_series, fill_value=0)
    except Exception as e:
        print(f"{rule:<14}  ERROR {e}")

print("-" * 115)
# Combined (sum of all 4 skew rules)
r = all_pnl.dropna()
ann_mean = r.mean() * 252
ann_std = r.std() * np.sqrt(252)
sharpe = ann_mean / ann_std if ann_std > 0 else 0
ds = r[r < 0].std() * np.sqrt(252)
sortino = ann_mean / ds if ds > 0 else 0
from scipy.stats import skew as scipy_skew, kurtosis as scipy_kurt
sk = float(scipy_skew(r))
kt = float(scipy_kurt(r, fisher=True))
hit = (r > 0).mean()
gain = r[r > 0].sum()
loss = -r[r < 0].sum()
pf = gain / loss if loss > 0 else 0
t = r.mean() / (r.std() / np.sqrt(len(r)))
print(f"{'ALL-SKEW':<14} {sharpe:>+8.3f} {sortino:>+8.3f} {ann_mean:>+8.0f} {ann_std:>+9.0f} "
      f"{r.mean():>+8.2f} {r.median():>+8.2f} {sk:>+7.2f} {kt:>+7.2f} "
      f"{hit:>6.3f} {pf:>6.3f} {t:>+7.2f}")

print(f"\nData span: {r.index.min().date()} → {r.index.max().date()} ({len(r)} days)")
print(f"Total 10yr P&L from skew alone: {r.sum():+,.0f}")

# Cumulative curves comparison
print("\n" + "=" * 60)
print("skew-only equity curve (sum of 4 rule contributions)")
print("=" * 60)
cum = r.cumsum()
dd = cum - cum.cummax()
print(f"  Peak gain from lowest:       ${cum.max() - cum.min():,.0f}")
print(f"  Max drawdown:                ${dd.min():,.0f}")
print(f"  Time in drawdown:            {(dd < 0).mean()*100:.1f}%")
print(f"  Worst day:                   ${r.min():,.0f}")
print(f"  Best day:                    ${r.max():,.0f}")
