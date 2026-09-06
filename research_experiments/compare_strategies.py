"""Compare Trend-only vs Carry-only vs Combined at $500k + dynamic opt.
Reuses signals.py's asset classes, weighting, cost filter, and instruments.
"""
import numpy as np
import pandas as pd
from scipy.stats import skew as scipy_skew

from sysdata.config.configdata import Config
from sysdata.data_blob import dataBlob
from sysdata.sim.futures_sim_data_with_data_blob import genericBlobUsingFuturesSimData
from sysdata.csv.csv_instrument_data import csvFuturesInstrumentData
from sysdata.csv.csv_roll_parameters import csvRollParametersData
from sysdata.csv.csv_spread_costs import csvSpreadCostData
from sysdata.csv.csv_spot_fx import csvFxPricesData
from sysdata.parquet.parquet_multiple_prices import parquetFuturesMultiplePricesData
from sysdata.parquet.parquet_adjusted_prices import parquetFuturesAdjustedPricesData
from syslogging.logger import get_logger
from systems.basesystem import System
from systems.forecasting import Rules
from systems.rawdata import RawData
from systems.forecast_combine import ForecastCombine
from systems.positionsizing import PositionSizing
from systems.portfolio import Portfolios
from systems.provided.attenuate_vol.vol_attenuation_forecast_scale_cap import (
    volAttenForecastScaleCap,
)
from systems.provided.dynamic_small_system_optimise.optimised_positions_stage import (
    optimisedPositions,
)
from systems.provided.dynamic_small_system_optimise.accounts_stage import (
    accountForOptimisedStage,
)


class parquetFuturesSimData(genericBlobUsingFuturesSimData):
    def __init__(self):
        data = dataBlob(
            log=get_logger("parquetFuturesSimData"),
            class_list=[
                parquetFuturesAdjustedPricesData,
                parquetFuturesMultiplePricesData,
                csvFuturesInstrumentData,
                csvFxPricesData,
                csvRollParametersData,
                csvSpreadCostData,
            ],
        )
        super().__init__(data=data)


bad_markets = {"US2", "US3", "US5", "EURCHF", "GBPEUR", "CAD", "SOFR1",
               "LUMBER-new", "OATIES", "STEEL",
               "BRENT_W", "GASOILINE", "HEATOIL", "CRUDE_W"}

_raw_asset_classes = {
    "Equity":       ["SP500", "NASDAQ", "RUSSELL", "DOW", "NIKKEI"],
    "FX":           ["EUR", "JPY", "GBP", "AUD", "NZD", "MXP", "CHF", "CAD",
                     "ZAR", "EURCHF", "GBPEUR", "BITCOIN", "ETHEREUM"],
    "Bond":         ["US2", "US3", "US5", "US10", "US10U", "US20", "US30", "SOFR1"],
    "Energy":       ["CRUDE_W", "BRENT_W", "GAS_US", "GASOILINE", "HEATOIL", "GAS-LAST"],
    "Metal":        ["GOLD", "SILVER", "COPPER", "PLAT", "PALLAD", "STEEL"],
    "Agricultural": ["REDWHEAT", "SOYMEAL", "SOYOIL", "OATIES", "RICE",
                     "LEANHOG", "LIVECOW", "FEEDCOW", "LUMBER-new"],
}
asset_classes = {c: [i for i in insts if i not in bad_markets]
                 for c, insts in _raw_asset_classes.items()}
N_TARGET_CLASSES = 7  # 7th = Volatility, empty, 1/7 stays in cash

all_instruments = [i for insts in asset_classes.values() for i in insts]
instrument_to_class = {i: c for c, insts in asset_classes.items() for i in insts}


def instrument_vol(code):
    s = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").squeeze()
    s = s.dropna().resample("1B").last().dropna().tail(500)
    s = s[s > 0]
    return float(s.pct_change().dropna().std() * np.sqrt(252))


vols = {i: instrument_vol(i) for i in all_instruments}

# 1/7 per class, inverse-vol within class, 5% cap
class_budget = 1.0 / N_TARGET_CLASSES
raw_w = {}
for cls, insts in asset_classes.items():
    if not insts: continue
    inv_vols = {i: 1.0 / max(vols[i], 1e-6) for i in insts}
    total = sum(inv_vols.values())
    for i in insts:
        raw_w[i] = class_budget * inv_vols[i] / total

deployed = sum(raw_w.values())
MAX_W = 0.05
scaled = {k: v / deployed for k, v in raw_w.items()}
capped = dict(scaled)
while True:
    over = {k: v for k, v in capped.items() if v > MAX_W / deployed}
    if not over: break
    excess = sum(v - MAX_W / deployed for v in over.values())
    under = {k: v for k, v in capped.items() if v <= MAX_W / deployed}
    if not under: break
    tot_u = sum(under.values())
    for k in over: capped[k] = MAX_W / deployed
    for k in under: capped[k] += excess * (under[k] / tot_u)
instrument_weights = {k: v * deployed for k, v in capped.items()}
instruments = list(instrument_weights.keys())


def build_and_run(label: str, forecast_weights: dict):
    print(f"\n{'=' * 70}\n=== {label} ===\n{'=' * 70}")
    config = Config("systems.provided.futures_chapter15.futuresconfig.yaml")
    config.instruments = instruments
    config.start_date = "2016-01-01"
    config.percentage_vol_target = 20.0
    config.notional_trading_capital = 500_000
    config.forecast_post_ceiling_cost_SR = 0.10
    config.instrument_weights = instrument_weights
    config.use_instrument_weight_estimates = False
    config.use_instrument_div_mult_estimates = True

    # Register carry rules
    for sd in [10, 30, 60, 125]:
        config.trading_rules[f"carry{sd}"] = {
            "function": "systems.provided.rules.carry.carry",
            "data": ["rawdata.raw_carry"],
            "other_args": {"smooth_days": sd},
        }

    config.forecast_weights = forecast_weights
    config.use_forecast_weight_estimates = False
    config.use_forecast_scale_estimates = True
    config.use_attenuation = list(forecast_weights.keys())

    system = System(
        [accountForOptimisedStage(), optimisedPositions(), Portfolios(),
         PositionSizing(), RawData(), ForecastCombine(),
         volAttenForecastScaleCap(), Rules()],
        parquetFuturesSimData(), config,
    )

    pnl = system.accounts.optimised_portfolio()
    stats = dict(pnl.stats()[0])
    port_sr = float(stats.get("sharpe", 0) or 0)
    port_ann = float(stats.get("ann_mean", 0) or 0)

    per_inst = {}
    for inst in instruments:
        try:
            p = system.accounts.pandl_for_optimised_instrument(inst)
            s = dict(p.stats()[0])
            per_inst[inst] = {
                "sr": float(s.get("sharpe", 0) or 0),
                "ann": float(s.get("ann_mean", 0) or 0),
                "class": instrument_to_class.get(inst, "?"),
            }
        except Exception:
            per_inst[inst] = {"sr": float("nan"), "ann": 0,
                              "class": instrument_to_class.get(inst, "?")}

    print(f"\nPortfolio Sharpe: {port_sr:+.3f}  |  Ann mean: ${port_ann:,.0f}")
    print(f"\n{'Class':14s}  {'n':>3s}  {'MeanSR':>7s}  {'Med SR':>7s}  "
          f"{'Stdev':>6s}  {'Skew':>6s}  {'Min':>6s}  {'Max':>6s}  {'TotAnn$':>9s}")
    class_rows = {}
    for cls, insts in asset_classes.items():
        srs = [per_inst[i]["sr"] for i in insts if i in per_inst and not np.isnan(per_inst[i]["sr"])]
        anns = [per_inst[i]["ann"] for i in insts if i in per_inst]
        if not srs: continue
        row = {
            "n": len(srs),
            "mean": float(np.mean(srs)),
            "med": float(np.median(srs)),
            "std": float(np.std(srs)) if len(srs) > 1 else 0,
            "skew": float(scipy_skew(srs)) if len(srs) > 2 else 0,
            "min": float(np.min(srs)),
            "max": float(np.max(srs)),
            "tot": float(np.sum(anns)),
        }
        class_rows[cls] = row
        print(f"{cls:14s}  {row['n']:>3d}  {row['mean']:>+7.3f}  {row['med']:>+7.3f}  "
              f"{row['std']:>6.3f}  {row['skew']:>+6.2f}  {row['min']:>+6.2f}  "
              f"{row['max']:>+6.2f}  {row['tot']:>+9,.0f}")

    return port_sr, port_ann, class_rows


# Three configs
trend_only = {"ewmac8_32": 0.25, "ewmac16_64": 0.25,
              "ewmac32_128": 0.25, "ewmac64_256": 0.25}
carry_only = {"carry10": 0.25, "carry30": 0.25, "carry60": 0.25, "carry125": 0.25}
combined   = {"ewmac8_32": 0.15, "ewmac16_64": 0.15, "ewmac32_128": 0.15, "ewmac64_256": 0.15,
              "carry10": 0.10, "carry30": 0.10, "carry60": 0.10, "carry125": 0.10}

results = {}
for label, wts in [("TREND-ONLY", trend_only), ("CARRY-ONLY", carry_only),
                   ("COMBINED 60/40", combined)]:
    results[label] = build_and_run(label, wts)

# Side-by-side per-class comparison
print(f"\n\n{'=' * 80}\n=== SIDE-BY-SIDE: Mean Sharpe by class ===\n{'=' * 80}")
print(f"{'Class':14s}  {'Trend':>8s}  {'Carry':>8s}  {'Combined':>10s}")
all_classes = sorted({c for _, _, rows in results.values() for c in rows})
for cls in all_classes:
    trend_sr = results["TREND-ONLY"][2].get(cls, {}).get("mean", float("nan"))
    carry_sr = results["CARRY-ONLY"][2].get(cls, {}).get("mean", float("nan"))
    comb_sr = results["COMBINED 60/40"][2].get(cls, {}).get("mean", float("nan"))
    print(f"{cls:14s}  {trend_sr:>+8.3f}  {carry_sr:>+8.3f}  {comb_sr:>+10.3f}")

print(f"\n{'Portfolio SR':14s}  {results['TREND-ONLY'][0]:>+8.3f}  "
      f"{results['CARRY-ONLY'][0]:>+8.3f}  {results['COMBINED 60/40'][0]:>+10.3f}")
print(f"{'Ann mean $':14s}  {results['TREND-ONLY'][1]:>+8,.0f}  "
      f"{results['CARRY-ONLY'][1]:>+8,.0f}  {results['COMBINED 60/40'][1]:>+10,.0f}")
