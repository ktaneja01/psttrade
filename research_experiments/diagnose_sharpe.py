"""Diagnose where Carver's 0.1 Sharpe comes from — break down by instrument, rule, and asset class."""
import numpy as np
import pandas as pd
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


asset_classes = {
    "Vol":    ["VIX", "V2X"],
    "Equity": ["SP500", "NASDAQ", "RUSSELL", "DOW", "EUROSTX", "DAX", "CAC", "FTSE100", "NIKKEI"],
    "FX":     ["EUR", "JPY", "GBP", "AUD", "NZD", "MXP", "CHF", "DX"],
    "Bond":   ["US2", "US5", "US10", "US20", "BUND", "BOBL", "GILT", "SHATZ"],
    "Energy": ["BRENT_W", "GAS_US", "GASOIL", "GASOILINE"],
    "Metals": ["GOLD", "SILVER", "COPPER", "PLAT", "PALLAD"],
    "Ags":    ["WHEAT", "SOYBEAN", "SOYMEAL", "SOYOIL", "COFFEE", "COCOA", "COTTON2", "SUGAR11",
               "LEANHOG", "LIVECOW", "FEEDCOW", "RICE", "OATIES", "OJ"],
    "Crypto": ["BITCOIN", "ETHEREUM"],
}

instruments = [i for insts in asset_classes.values() for i in insts]
instrument_to_class = {i: cls for cls, insts in asset_classes.items() for i in insts}

config = Config("systems.provided.futures_chapter15.futuresconfig.yaml")
config.instruments = instruments
config.start_date = "2021-01-01"
config.percentage_vol_target = 20.0
config.notional_trading_capital = 250_000
config.forecast_post_ceiling_cost_SR = 0.13
config.instrument_weights = {i: 1.0 / len(instruments) for i in instruments}
config.use_instrument_weight_estimates = False
config.use_instrument_div_mult_estimates = False
config.instrument_div_multiplier = 1.0
config.forecast_weights = {
    "ewmac16_64": 0.20, "ewmac32_128": 0.20, "ewmac64_256": 0.20, "carry": 0.40,
}
config.use_forecast_weight_estimates = False

system = System(
    [Account(), Portfolios(), PositionSizing(), RawData(), ForecastCombine(), ForecastScaleCap(), Rules()],
    csvFuturesSimData(), config,
)

# ============================================================
# 1. Per-instrument subsystem Sharpe (unweighted — pure alpha per instrument)
# ============================================================
print("=" * 70)
print("1. Per-instrument subsystem Sharpe (pure rule+carry alpha per instrument)")
print("=" * 70)
per_inst = {}
for i in instruments:
    try:
        pnl = system.accounts.pandl_for_subsystem(i)
        stats = dict(pnl.stats()[0])
        per_inst[i] = {
            "sharpe": float(stats.get("sharpe", 0) or 0),
            "ann_mean": float(stats.get("ann_mean", 0) or 0),
            "ann_std": float(stats.get("ann_std", 0) or 0),
        }
    except Exception as e:
        per_inst[i] = {"sharpe": np.nan, "ann_mean": np.nan, "ann_std": np.nan}

rows = sorted(per_inst.items(), key=lambda kv: -kv[1]["sharpe"] if not np.isnan(kv[1]["sharpe"]) else -999)
print(f"\n{'Instrument':12s} {'Class':8s} {'Sharpe':>8s} {'Ann$':>10s} {'Ann std':>10s}")
for inst, d in rows:
    cls = instrument_to_class.get(inst, "?")
    print(f"{inst:12s} {cls:8s} {d['sharpe']:>+8.3f} {d['ann_mean']:>+10.0f} {d['ann_std']:>10.0f}")

# Summary stats
sharpes = [d["sharpe"] for d in per_inst.values() if not np.isnan(d["sharpe"])]
positive = sum(1 for s in sharpes if s > 0)
print(f"\nPositive Sharpe:   {positive}/{len(sharpes)}")
print(f"Mean Sharpe:       {np.mean(sharpes):+.3f}")
print(f"Median Sharpe:     {np.median(sharpes):+.3f}")
print(f"Std of Sharpes:    {np.std(sharpes):.3f}")

# ============================================================
# 2. Per-asset-class summary
# ============================================================
print("\n" + "=" * 70)
print("2. Per-asset-class subsystem Sharpe (equal-weight within class)")
print("=" * 70)
print(f"\n{'Asset class':10s} {'# inst':>8s} {'Mean Sharpe':>12s} {'Median':>10s} {'% positive':>12s}")
for cls, insts in asset_classes.items():
    class_sharpes = [per_inst[i]["sharpe"] for i in insts if i in per_inst and not np.isnan(per_inst[i]["sharpe"])]
    if not class_sharpes:
        continue
    pos_pct = sum(1 for s in class_sharpes if s > 0) / len(class_sharpes) * 100
    print(f"{cls:10s} {len(class_sharpes):>8d} {np.mean(class_sharpes):>+12.3f} {np.median(class_sharpes):>+10.3f} {pos_pct:>11.0f}%")

# ============================================================
# 3. Per-rule performance (pool across all instruments)
# ============================================================
print("\n" + "=" * 70)
print("3. Per-rule Sharpe (pooled across all 52 instruments)")
print("=" * 70)
rules = ["ewmac16_64", "ewmac32_128", "ewmac64_256", "carry"]
for rule in rules:
    rule_sharpes = []
    rule_returns = []
    for i in instruments:
        try:
            pnl = system.accounts.pandl_for_instrument_forecast(i, rule)
            s = dict(pnl.stats()[0])
            sharpe = float(s.get("sharpe", 0) or 0)
            ann_mean = float(s.get("ann_mean", 0) or 0)
            if not np.isnan(sharpe):
                rule_sharpes.append(sharpe)
                rule_returns.append(ann_mean)
        except Exception:
            pass
    if rule_sharpes:
        positive = sum(1 for s in rule_sharpes if s > 0)
        print(f"  {rule:15s}  mean Sharpe={np.mean(rule_sharpes):+.3f}  median={np.median(rule_sharpes):+.3f}  "
              f"positive={positive}/{len(rule_sharpes)}  avg ann$={np.mean(rule_returns):+.0f}")

print("\nDone.")
