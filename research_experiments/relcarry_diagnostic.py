"""Pull 10yr backtest stats per relcarry variant, aggregated across all instruments.

Uses pysystemtrade's pandl_for_trading_rule_weighted — aggregates each rule's
P&L across instruments using the live forecast_weights × instrument_weights.
"""
import os
os.environ["CAPITAL"] = "500000"

# Build the full system from signals.py (everything up to the System() construction)
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

print("\n\n" + "=" * 100)
print("relcarry 10yr backtest stats (weighted across all instruments)")
print("=" * 100)
hdr = f"{'Rule':<14} {'Sharpe':>8} {'Sortino':>8} {'Ann $':>10} {'Ann std':>10} "
hdr += f"{'Skew':>7} {'Avg DD':>10} {'HitRate':>8} {'ProfitF':>8} {'t-stat':>7} {'Turnover':>9}"
print(hdr)
print("-" * 100)

for rule in ["ewmac8_32", "ewmac16_64", "ewmac32_128", "ewmac64_256",
             "accel16", "accel32", "accel64",
             "breakout20", "breakout40", "breakout80", "breakout160"]:
    p = system.accounts.pandl_for_trading_rule_weighted(rule)
    s = dict(p.stats()[0])
    sharpe   = float(s.get("sharpe", 0) or 0)
    sortino  = float(s.get("sortino", 0) or 0)
    ann_mean = float(s.get("ann_mean", 0) or 0)
    ann_std  = float(s.get("ann_std", 0) or 0)
    skew     = float(s.get("skew", 0) or 0)
    avg_dd   = float(s.get("avg_drawdown", 0) or 0)
    hitrate  = float(s.get("hitrate", 0) or 0)
    pf       = float(s.get("profitfactor", 0) or 0)
    t_stat   = float(s.get("t_stat", 0) or 0)
    # Turnover: count sign changes in forecast as rough proxy — use pysystemtrade's
    try:
        turnover = system.accounts.forecast_turnover_for_list([rule]).iloc[0, 0]
    except Exception:
        turnover = float("nan")

    print(f"{rule:<14} {sharpe:>+8.3f} {sortino:>+8.3f} {ann_mean:>+10.0f} {ann_std:>+10.0f} "
          f"{skew:>+7.2f} {avg_dd:>+10.0f} {hitrate:>8.3f} {pf:>8.3f} {t_stat:>+7.2f} {turnover:>9.2f}")

print("\n(Sharpe/stats on net P&L after costs, weighted by forecast_weight × instrument_weight)")
