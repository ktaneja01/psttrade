"""Generate full-sample and OOS equity curves, drawdowns, and rolling Sharpe."""
import os
os.environ["CAPITAL"] = "200000"

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

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

CAPITAL = int(os.environ["CAPITAL"])
OOS_START = "2024-01-01"

r = pd.Series(system.accounts.portfolio().percent).astype(float) / 100.0
r = r.dropna()
pnl = r * CAPITAL
equity = CAPITAL + pnl.cumsum()
dd = (equity - equity.cummax()) / equity.cummax() * 100

# Rolling 252d Sharpe
roll_sharpe = (r.rolling(252).mean() / r.rolling(252).std()) * np.sqrt(252)

# ============================================================
# Plot 1: Full-sample equity + drawdown with OOS shaded
# ============================================================
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True,
                                gridspec_kw={"height_ratios": [3, 1]})

ax1.plot(equity.index, equity.values, linewidth=1.3, color="#1f77b4", label="Equity")
ax1.axhline(CAPITAL, color="gray", linestyle="--", alpha=0.4, linewidth=0.8)
ax1.axvspan(pd.Timestamp(OOS_START), equity.index[-1],
             alpha=0.12, color="orange", label="OOS (2024-2026)")
ax1.set_ylabel("Equity ($)")
ax1.set_title(f"System equity curve ($500K capital)  |  "
              f"Sharpe in-sample {r.mean()/r.std()*np.sqrt(252):+.2f}  "
              f"|  Sharpe OOS {r[r.index>=OOS_START].mean()/r[r.index>=OOS_START].std()*np.sqrt(252):+.2f}")
ax1.legend(loc="upper left")
ax1.grid(alpha=0.3)
ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f"${x/1000:.0f}K"))

ax2.fill_between(dd.index, dd.values, 0, color="#d62728", alpha=0.5)
ax2.axvspan(pd.Timestamp(OOS_START), dd.index[-1], alpha=0.12, color="orange")
ax2.set_ylabel("Drawdown (%)")
ax2.set_xlabel("Date")
ax2.grid(alpha=0.3)
ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f"{x:.0f}%"))

plt.tight_layout()
plt.savefig("/tmp/equity_curve_full.png", dpi=120)
plt.close()
print("Saved /tmp/equity_curve_full.png")

# ============================================================
# Plot 2: OOS-only equity curve (reindexed to $500K at Jan 2024)
# ============================================================
r_oos = r[r.index >= OOS_START]
pnl_oos = r_oos * CAPITAL
eq_oos = CAPITAL + pnl_oos.cumsum()
dd_oos = (eq_oos - eq_oos.cummax()) / eq_oos.cummax() * 100

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True,
                                gridspec_kw={"height_ratios": [3, 1]})

ax1.plot(eq_oos.index, eq_oos.values, linewidth=1.3, color="#2ca02c")
ax1.axhline(CAPITAL, color="gray", linestyle="--", alpha=0.4, linewidth=0.8)
ax1.set_ylabel("Equity ($)")
oos_sharpe = r_oos.mean()/r_oos.std()*np.sqrt(252)
oos_ret = (eq_oos.iloc[-1]/CAPITAL - 1) * 100
oos_maxdd = dd_oos.min()
ax1.set_title(f"OOS equity curve 2024-2026  |  Sharpe {oos_sharpe:+.2f}  "
              f"|  Total return {oos_ret:+.1f}%  |  Max DD {oos_maxdd:.1f}%")
ax1.grid(alpha=0.3)
ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f"${x/1000:.0f}K"))

ax2.fill_between(dd_oos.index, dd_oos.values, 0, color="#d62728", alpha=0.5)
ax2.set_ylabel("Drawdown (%)")
ax2.set_xlabel("Date")
ax2.grid(alpha=0.3)
ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f"{x:.0f}%"))

plt.tight_layout()
plt.savefig("/tmp/equity_curve_oos.png", dpi=120)
plt.close()
print("Saved /tmp/equity_curve_oos.png")

print(f"\nOOS worst-drawdown-only (reset at 2024-01-01): {oos_maxdd:.2f}%")
print(f"OOS total return:                               {oos_ret:+.2f}%")
print(f"OOS Sharpe:                                     {oos_sharpe:+.3f}")

# ============================================================
# Plot 3: Rolling 1-year Sharpe
# ============================================================
fig, ax = plt.subplots(figsize=(14, 5))
ax.plot(roll_sharpe.index, roll_sharpe.values, linewidth=1.2, color="#9467bd")
ax.axhline(0, color="gray", linestyle="--", alpha=0.4)
ax.axhline(roll_sharpe.mean(), color="blue", linestyle=":", alpha=0.6,
           label=f"Long-run mean {roll_sharpe.mean():+.2f}")
ax.axvspan(pd.Timestamp(OOS_START), roll_sharpe.index[-1], alpha=0.12, color="orange",
           label="OOS")
ax.set_ylabel("Rolling 1-year Sharpe")
ax.set_title("Rolling 252-day Sharpe — system portfolio")
ax.legend(loc="upper left")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig("/tmp/rolling_sharpe.png", dpi=120)
plt.close()
print("Saved /tmp/rolling_sharpe.png")
