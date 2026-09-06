"""Compute handcraft_shrunk weights and forecast scalars using ONLY data up to
end-2023. Output the dicts for pasting into signals.py to run a true
out-of-sample 2024–2026 backtest.
"""
import os
os.environ["CAPITAL"] = "500000"

import numpy as np
import pandas as pd

CUTOFF = "2023-12-31"

# =========================================================================
# Part 1 — Handcraft_shrunk weights using only 2016-2023 returns
# =========================================================================
from sysquant.estimators.correlations import correlationEstimate
from sysquant.estimators.mean_estimator import meanEstimates
from sysquant.estimators.stdev_estimator import stdevEstimates
from sysquant.estimators.estimates import Estimates
from sysquant.optimisation.optimisers.handcraft import handcraft_optimisation

bad_markets = {"US2", "US3", "US5", "EURCHF", "GBPEUR", "CAD", "SOFR1",
               "LUMBER-new", "OATIES", "STEEL", "BRENT_W",
               "SHATZ", "BOBL", "COTTON2", "SUGAR11",
               "SP500", "GOLD"}

_raw = {
    "Bonds": ["US2","US3","US5","US10","US10U","US20","US30","SOFR1","BOBL","BUND","SHATZ","GILT"],
    "Grains": ["REDWHEAT","SOYMEAL","SOYOIL","WHEAT","CORN","SOYBEAN","OATIES"],
    "Energy-Livestock": ["CRUDE_W","BRENT_W","GAS_US","GASOILINE","HEATOIL","GAS-LAST",
                         "LIVECOW","FEEDCOW","LEANHOG","RICE","LUMBER-new","GBPJPY",
                         "COFFEE","OJ","GASOIL","COCOA"],
    "Equity-Risk": ["SP500","NASDAQ","RUSSELL","DOW","NIKKEI","SP400",
                    "CAC","DAX","EUROSTX","FTSE100","VIX","V2X"],
    "G10-FX": ["EUR","JPY","GBP","AUD","NZD","CHF","CAD","EURCHF","GBPEUR","PLN","EURCAD","DX"],
    "EM-Metal-Crypto": ["MXP","ZAR","BRE","GOLD","SILVER","COPPER","PLAT","PALLAD","STEEL","BITCOIN","ETHEREUM"],
}
instruments = [i for insts in _raw.values() for i in insts if i not in bad_markets]

def weekly_rets(code):
    s = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").squeeze()
    s = s.dropna().resample("1B").last().ffill()
    s = s[s > 0]
    r = s.pct_change().dropna()
    return r.resample("W").sum().rename(code)

rets = pd.concat([weekly_rets(i) for i in instruments], axis=1)
rets = rets[(rets.index >= "2016-01-01") & (rets.index <= CUTOFF)]
rets = rets.dropna(thresh=int(len(instruments) * 0.5)).fillna(0)
print(f"Weight estimation data: {len(rets)} weeks, {rets.index.min().date()} → {rets.index.max().date()}")

corr_df = rets.corr()
vols = rets.std() * np.sqrt(52)
means = rets.mean() * 52

est = Estimates(
    correlation=correlationEstimate(values=corr_df.values, columns=list(corr_df.columns)),
    mean=meanEstimates({i: float(means[i]) for i in instruments}),
    stdev=stdevEstimates({i: float(vols[i]) for i in instruments}),
    data_length=len(rets),
    frequency="W",
)
est = est.shrink_correlation_to_average(0.5)
out = handcraft_optimisation(est, equalise_SR=True, equalise_vols=True)
raw_w = dict(out.weights)

def cap_weights(w, cap=0.05):
    w = dict(w)
    while True:
        over = {k:v for k,v in w.items() if v > cap}
        if not over: break
        excess = sum(v-cap for v in over.values())
        under = {k:v for k,v in w.items() if v <= cap}
        if not under: break
        under_total = sum(under.values())
        for k in over: w[k] = cap
        for k in under: w[k] += excess * (under[k]/under_total)
    total = sum(w.values())
    return {k: v/total for k,v in w.items()}

frozen_w = cap_weights(raw_w, 0.05)

print("\n# --- weights (data 2016-2023) ---")
print("FROZEN_HANDCRAFT_SHRUNK_WEIGHTS_2023 = {")
for k in sorted(frozen_w, key=lambda x: -frozen_w[x]):
    print(f'    "{k}": {frozen_w[k]:.6f},')
print("}")

# =========================================================================
# Part 2 — Scalars as-of-2023-12-31 from the rolling estimator
# =========================================================================
print("\nBuilding system to read 2023-cutoff scalars...")

# Force estimator ON regardless of signals.py setting
os.environ["_FORCE_SCALAR_EST"] = "1"
exec(open("signals.py").read().split("# Build system with dynamic optimisation")[0])

config.use_forecast_scale_estimates = True  # override the frozen setting
# Remove any per-rule fixed scalar so estimator runs freely
for r_name, r_cfg in list(config.trading_rules.items()):
    if "forecast_scalar" in r_cfg:
        del r_cfg["forecast_scalar"]

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

all_rules = ["spot_trend8_32","spot_trend16_64","spot_trend32_128","spot_trend64_256",
             "accel8","accel16","accel32","accel64",
             "breakout20","breakout40","breakout80","breakout160",
             "carry10","carry30","carry60","carry125",
             "relcarry10","relcarry30","relcarry60","relcarry125",
             "carry_accel10","carry_accel30","carry_accel60","carry_accel125"]

# Pick any instrument; since estimator is pooled, value is the same across instruments
probe_inst = "BUND"
frozen_scalars_2023 = {}
for r in all_rules:
    s = system.forecastScaleCap.get_forecast_scalar(probe_inst, r)
    s = s.dropna()
    val = s.loc[:CUTOFF].iloc[-1] if len(s.loc[:CUTOFF]) else np.nan
    frozen_scalars_2023[r] = float(val)

print("\n# --- scalars (as-of 2023-12-31, pooled) ---")
print("FROZEN_SCALARS_2023 = {")
for r in all_rules:
    print(f'    "{r}": {frozen_scalars_2023[r]:.3f},')
print("}")
