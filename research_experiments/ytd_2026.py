"""Year-to-date 2026 simulation slice, equity curve + stats."""
import os
os.environ["CAPITAL"] = "500000"

import numpy as np
import pandas as pd
from scipy.stats import skew as scipy_skew, kurtosis as scipy_kurt
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

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
     RawData(), ForecastCombine(), volAttenForecastScaleCap(), Rules()],
    parquetFuturesSimData(), config,
)

CAPITAL = 500_000
YTD_START = "2026-01-01"

r = pd.Series(system.accounts.portfolio().percent).astype(float) / 100.0
r = r.dropna()
r_ytd = r[r.index >= YTD_START]
pnl_ytd = r_ytd * CAPITAL

# Stats
n = len(r_ytd)
ann_mean_pct = r_ytd.mean() * 252
ann_std_pct = r_ytd.std() * np.sqrt(252)
sharpe = ann_mean_pct / ann_std_pct if ann_std_pct > 0 else 0
total_return = r_ytd.sum() * 100

cum_pnl = pnl_ytd.cumsum()
equity = CAPITAL + cum_pnl
dd = (equity - equity.cummax()) / equity.cummax() * 100

# Downside vol
ds = r_ytd[r_ytd < 0].std() * np.sqrt(252)
sortino = ann_mean_pct / ds if ds > 0 else 0
sk = float(scipy_skew(r_ytd))
kt = float(scipy_kurt(r_ytd, fisher=True))
hit = (r_ytd > 0).mean()

print(f"\n{'=' * 60}")
print(f"YTD 2026 simulation — {YTD_START} to {r_ytd.index.max().date()}")
print(f"{'=' * 60}")
print(f"  Trading days:                    {n}")
print(f"  Total return:                    {total_return:+.2f}%")
print(f"  Total P&L $:                     {cum_pnl.iloc[-1]:+,.0f}")
print(f"  Ending equity:                   ${equity.iloc[-1]:,.0f}")
print(f"")
print(f"  Annualized return:               {ann_mean_pct*100:+.2f}%")
print(f"  Annualized vol:                  {ann_std_pct*100:.2f}%")
print(f"  Sharpe:                          {sharpe:+.3f}")
print(f"  Sortino:                         {sortino:+.3f}")
print(f"")
print(f"  Skew:                            {sk:+.2f}")
print(f"  Excess kurtosis:                 {kt:+.2f}")
print(f"  Hit rate:                        {hit*100:.1f}%")
print(f"  Worst day:                       {r_ytd.min()*100:+.2f}%")
print(f"  Best day:                        {r_ytd.max()*100:+.2f}%")
print(f"  Max drawdown:                    {dd.min():.2f}%")

# Equity curve plot
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 7), sharex=True,
                                gridspec_kw={"height_ratios": [3, 1]})

ax1.plot(equity.index, equity.values, linewidth=1.4, color="#2ca02c")
ax1.axhline(CAPITAL, color="gray", linestyle="--", alpha=0.4)
ax1.fill_between(equity.index, CAPITAL, equity.values, where=(equity.values >= CAPITAL),
                 color="#2ca02c", alpha=0.12)
ax1.fill_between(equity.index, CAPITAL, equity.values, where=(equity.values < CAPITAL),
                 color="#d62728", alpha=0.12)
ax1.set_ylabel("Equity ($)")
ax1.set_title(f"YTD 2026 — $500K capital  |  Sharpe {sharpe:+.2f}  |  "
              f"Total return {total_return:+.2f}% ({cum_pnl.iloc[-1]:+,.0f})")
ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f"${x/1000:.0f}K"))
ax1.grid(alpha=0.3)

ax2.fill_between(dd.index, dd.values, 0, color="#d62728", alpha=0.5)
ax2.set_ylabel("Drawdown (%)")
ax2.set_xlabel("Date")
ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f"{x:.0f}%"))
ax2.grid(alpha=0.3)

plt.tight_layout()
plt.savefig("/tmp/ytd_2026_equity.png", dpi=120)
print(f"\nEquity curve saved to /tmp/ytd_2026_equity.png")
