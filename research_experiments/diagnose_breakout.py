"""Diagnose breakout rule performance on our instrument set."""
import numpy as np
from sysdata.config.configdata import Config
from sysdata.sim.csv_futures_sim_data import csvFuturesSimData
from systems.basesystem import System
from systems.forecasting import Rules
from systems.rawdata import RawData
from systems.forecast_combine import ForecastCombine
from systems.forecast_scale_cap import ForecastScaleCap
from systems.positionsizing import PositionSizing
from systems.portfolio import Portfolios
from systems.accounts.accounts_stage import Account

instruments = ["SP500", "NIKKEI", "CRUDE_W", "GOLD", "JPY", "COFFEE", "US10",
               "BUND", "COCOA", "NASDAQ", "BRENT_W", "COPPER"]

config = Config("systems.provided.futures_chapter15.futuresconfig.yaml")
config.instruments = instruments
config.start_date = "2021-01-01"
config.percentage_vol_target = 20.0
config.notional_trading_capital = 250_000
config.instrument_weights = {i: 1.0 / len(instruments) for i in instruments}
config.use_instrument_weight_estimates = False
config.use_instrument_div_mult_estimates = False
config.instrument_div_multiplier = 1.0

# Add breakout rules
config.trading_rules = dict(config.trading_rules)
for lb, scalar in [(40, 0.70), (80, 0.73), (160, 0.74), (320, 0.74)]:
    config.trading_rules[f"breakout{lb}"] = {
        "function": "systems.provided.rules.breakout.breakout",
        "data": ["rawdata.get_daily_prices"],
        "other_args": {"lookback": lb},
        "forecast_scalar": scalar,
    }

config.forecast_weights = {
    "ewmac16_64": 0.1667, "ewmac32_128": 0.1667, "ewmac64_256": 0.1667,
    "carry": 0.40,
    "breakout40": 0.025, "breakout80": 0.025, "breakout160": 0.025, "breakout320": 0.025,
}
config.use_forecast_weight_estimates = False
config.forecast_post_ceiling_cost_SR = 0.13

system = System(
    [Account(), Portfolios(), PositionSizing(), RawData(), ForecastCombine(), ForecastScaleCap(), Rules()],
    csvFuturesSimData(), config,
)

print("Per-rule Sharpe across a sample of instruments")
rules = ["ewmac16_64", "ewmac32_128", "ewmac64_256", "carry",
         "breakout40", "breakout80", "breakout160", "breakout320"]

print(f"\n{'Rule':15s}", end=" ")
for i in instruments[:8]:
    print(f"{i:>9s}", end=" ")
print("  | avg")

for rule in rules:
    sharpes = []
    print(f"{rule:15s}", end=" ")
    for i in instruments[:8]:
        try:
            pnl = system.accounts.pandl_for_instrument_forecast(i, rule)
            s = dict(pnl.stats()[0])
            sharpe = float(s.get("sharpe", 0) or 0)
            sharpes.append(sharpe)
            print(f"{sharpe:>+9.2f}", end=" ")
        except Exception as e:
            print(f"{'  N/A':>9s}", end=" ")
    all_sharpes = []
    for i in instruments:
        try:
            pnl = system.accounts.pandl_for_instrument_forecast(i, rule)
            s = dict(pnl.stats()[0])
            all_sharpes.append(float(s.get("sharpe", 0) or 0))
        except:
            pass
    if all_sharpes:
        print(f"  | {np.mean(all_sharpes):+.3f}")
    else:
        print("  | N/A")

# Cost per rule
print("\nSR cost per rule (average across instruments)")
for rule in rules:
    costs = []
    for i in instruments:
        try:
            costs.append(system.accounts.get_SR_cost_for_instrument_forecast(i, rule))
        except:
            pass
    if costs:
        print(f"  {rule:15s}: avg SR cost = {np.mean(costs):.4f}")
