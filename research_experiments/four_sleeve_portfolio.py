"""4-sleeve portfolio:
  - 250K long SPY (SP500 futures)
  - 250K of our system
  - 125K long US2
  - 125K long GOLD
Total = 750K capital.
"""
import os
os.environ["CAPITAL"] = "250000"  # for the system sleeve

import numpy as np
import pandas as pd
from scipy.stats import skew as scipy_skew, kurtosis as scipy_kurt

SLEEVES = {
    "SPY (SP500)": 250_000,
    "System":      250_000,
    "Cash":        125_000,
    "Gold":        125_000,
}
TOTAL = sum(SLEEVES.values())
print(f"Total portfolio: ${TOTAL:,}")

# ============================================================
# 1. Long buy-and-hold returns for SPY / US2 / Gold
# ============================================================
def buy_hold_daily_dollar_pnl(instrument_code: str, sleeve_notional: float) -> pd.Series:
    """Constant-notional long buy-and-hold: daily $ P&L = sleeve × daily_return."""
    s = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{instrument_code}.parquet").squeeze()
    s = s.dropna().resample("1B").last().ffill()
    s = s[s > 0]
    rets = s.pct_change().dropna()
    return rets * sleeve_notional

print("\n[1/3] Building buy-and-hold sleeves...")
spy_pnl  = buy_hold_daily_dollar_pnl("SP500", 250_000)
gold_pnl = buy_hold_daily_dollar_pnl("GOLD",  125_000)
# Cash: assume 3% annualized risk-free rate (avg 2018-2026, blended across ZIRP and hike cycle)
CASH_RATE = 0.03
cash_daily_ret = CASH_RATE / 252
cash_pnl = pd.Series(cash_daily_ret * 125_000, index=spy_pnl.index, name="Cash")
print(f"  SPY  range: {spy_pnl.index.min().date()} → {spy_pnl.index.max().date()}, {len(spy_pnl)} days")
print(f"  Cash: flat @ {CASH_RATE*100}% annualized = ${cash_daily_ret * 125_000:.2f}/day")
print(f"  Gold range: {gold_pnl.index.min().date()} → {gold_pnl.index.max().date()}, {len(gold_pnl)} days")

# ============================================================
# 2. System daily $ P&L at 250K
# ============================================================
print("\n[2/3] Building system sleeve (running signals.py at 250K)...")
exec(open("signals.py").read().split("# Build system with dynamic optimisation")[0])
from systems.basesystem import System
from systems.provided.dynamic_small_system_optimise.optimised_positions_stage import optimisedPositions
from systems.provided.dynamic_small_system_optimise.accounts_stage import accountForOptimisedStage

system = System(
    [accountForOptimisedStage(), optimisedPositions(), Portfolios(), PositionSizing(),
     myFuturesRawData(), ForecastCombine(), volAttenForecastScaleCap(), Rules()],
    parquetFuturesSimData(), config,
)

p = system.accounts.optimised_portfolio()
system_pnl = p.as_ts.dropna()  # dollar P&L at 250K capital
print(f"  System P&L range: {system_pnl.index.min().date()} → {system_pnl.index.max().date()}, {len(system_pnl)} days")

# ============================================================
# 3. Combine sleeves
# ============================================================
print("\n[3/3] Combining sleeves...")
df = pd.DataFrame({
    "SPY":    spy_pnl,
    "System": system_pnl,
    "Cash":   cash_pnl,
    "Gold":   gold_pnl,
}).dropna(how="all")

# Sum daily $ P&L across all 4 sleeves
df["Total"] = df[["SPY","System","Cash","Gold"]].sum(axis=1)

# Limit to range where ALL sleeves have data
df_all = df.dropna()
print(f"  Common window: {df_all.index.min().date()} → {df_all.index.max().date()}, {len(df_all)} days")

# ============================================================
# Stats
# ============================================================
def compute_stats(pnl: pd.Series, capital: float, label: str):
    pct = pnl / capital
    ann_mean = pct.mean() * 252
    ann_std = pct.std() * np.sqrt(252)
    sharpe = ann_mean / ann_std if ann_std > 0 else 0
    ds = pct[pct < 0].std() * np.sqrt(252)
    sortino = ann_mean / ds if ds > 0 else 0
    cum = pnl.cumsum()
    dd = cum - cum.cummax()
    max_dd = dd.min()
    return {
        "label": label,
        "sharpe": sharpe,
        "sortino": sortino,
        "ann_mean_pct": ann_mean * 100,
        "ann_std_pct": ann_std * 100,
        "ann_mean_dollar": ann_mean * capital,
        "max_dd": max_dd,
        "max_dd_pct": max_dd / capital * 100,
        "worst_day_pct": pct.min() * 100,
        "best_day_pct": pct.max() * 100,
        "hit_rate": (pct > 0).mean() * 100,
    }

# Per-sleeve stats
print("\n" + "="*85)
print(f"{'Sleeve':<15} {'Sharpe':>8} {'Sortino':>8} {'AnnMean%':>10} {'AnnStd%':>9} {'AnnMean$':>12} {'MaxDD%':>8}")
print("-"*85)
sleeves_stats = []
for name, notional in SLEEVES.items():
    col = name.split(" ")[0]  # "SPY" from "SPY (SP500)"
    sub = df_all[col]
    st = compute_stats(sub, notional, name)
    sleeves_stats.append(st)
    print(f"{name:<15} {st['sharpe']:>+8.3f} {st['sortino']:>+8.3f} "
          f"{st['ann_mean_pct']:>+9.2f}% {st['ann_std_pct']:>+8.2f}% "
          f"{st['ann_mean_dollar']:>+12.0f} {st['max_dd_pct']:>+7.2f}%")

# Combined stats
total_st = compute_stats(df_all["Total"], TOTAL, "TOTAL")
print("-"*85)
print(f"{'TOTAL':<15} {total_st['sharpe']:>+8.3f} {total_st['sortino']:>+8.3f} "
      f"{total_st['ann_mean_pct']:>+9.2f}% {total_st['ann_std_pct']:>+8.2f}% "
      f"{total_st['ann_mean_dollar']:>+12.0f} {total_st['max_dd_pct']:>+7.2f}%")

# OOS slice
oos = df_all[df_all.index >= "2024-01-01"]
if len(oos) > 50:
    print("\n" + "="*85)
    print(f"OOS 2024-2026 (n={len(oos)} days)")
    print("-"*85)
    for col, sleeve_name in [("SPY","SPY"),("System","System"),("Cash","Cash"),("Gold","Gold"),("Total","TOTAL")]:
        notional = TOTAL if sleeve_name == "TOTAL" else SLEEVES[next(k for k in SLEEVES if k.startswith(sleeve_name))]
        st = compute_stats(oos[col], notional, sleeve_name)
        print(f"{sleeve_name:<15} {st['sharpe']:>+8.3f} {st['sortino']:>+8.3f} "
              f"{st['ann_mean_pct']:>+9.2f}% {st['ann_std_pct']:>+8.2f}% "
              f"{st['ann_mean_dollar']:>+12.0f} {st['max_dd_pct']:>+7.2f}%")

# Correlation matrix
print("\n" + "="*85)
print("Pairwise daily-return correlations")
print("-"*85)
# Correlation of $ P&L (Cash excluded since flat)
corr = df_all[["SPY","System","Gold"]].corr()
print(corr.round(3).to_string())

# Save time series to csv for inspection
df_all.to_csv("/tmp/four_sleeve_daily_pnl.csv")
print(f"\nSaved daily P&L time series to /tmp/four_sleeve_daily_pnl.csv")
