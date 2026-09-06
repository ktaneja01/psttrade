"""Compute shrinkage optimiser weights on the 55-instrument universe."""
import numpy as np
import pandas as pd
from sysquant.estimators.estimates import Estimates
from sysquant.estimators.correlations import correlationEstimate
from sysquant.estimators.mean_estimator import meanEstimates
from sysquant.estimators.stdev_estimator import stdevEstimates
from sysquant.optimisation.optimisers.shrinkage import shrinkage_optimisation

asset_classes = {
    "Bonds":            ["US10", "US10U", "US20", "US30", "BUND", "GILT"],
    "Grains":           ["REDWHEAT", "SOYMEAL", "SOYOIL", "WHEAT", "CORN", "SOYBEAN"],
    "Energy-Livestock": ["CRUDE_W", "GAS_US", "GASOILINE", "HEATOIL", "GAS-LAST",
                         "LIVECOW", "FEEDCOW", "LEANHOG", "RICE", "GBPJPY",
                         "COFFEE", "OJ", "GASOIL"],
    "Equity-Risk":      ["SP500", "NASDAQ", "RUSSELL", "DOW", "NIKKEI", "SP400",
                         "CAC", "DAX", "EUROSTX", "FTSE100", "VIX", "V2X"],
    "G10-FX":           ["EUR", "JPY", "GBP", "AUD", "NZD", "CHF", "PLN", "EURCAD"],
    "EM-Metal-Crypto":  ["MXP", "ZAR", "BRE", "GOLD", "SILVER", "COPPER", "PLAT", "PALLAD",
                         "BITCOIN", "ETHEREUM"],
}
instruments = [i for insts in asset_classes.values() for i in insts]
instrument_to_class = {i: c for c, insts in asset_classes.items() for i in insts}

def daily_returns(code):
    s = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").squeeze()
    s = s.dropna().resample("1B").last().ffill()
    s = s[s > 0]
    return s.pct_change().dropna().rename(code)

returns_df = pd.concat([daily_returns(i) for i in instruments], axis=1)
returns_df = returns_df[returns_df.index >= "2016-01-01"].dropna(thresh=int(len(instruments) * 0.5)).fillna(0)
weekly = returns_df.resample("W").sum()

corr = correlationEstimate(weekly.corr(), list(weekly.columns))
est = Estimates(
    correlation=corr,
    mean=meanEstimates(dict(weekly.mean() * 52)),
    stdev=stdevEstimates(dict(weekly.std() * np.sqrt(52))),
    data_length=len(weekly), frequency="W",
)

# Use separate instance for vol display
vols = {i: float(returns_df[i].std() * np.sqrt(252)) for i in instruments}

# Run shrinkage with same settings as our backtest (equalise_SR=True)
result = shrinkage_optimisation(
    est,
    shrinkage_SR=0.9,
    shrinkage_corr=0.5,
    ann_target_SR=0.5,
    equalise_SR=True,
    equalise_vols=True,
)

weights = dict(result.weights)
total = sum(abs(v) for v in weights.values())
weights = {k: v/total for k, v in weights.items()}

print("=" * 80)
print("SHRINKAGE WEIGHTS (equalise_SR=True, shrinkage_corr=0.5)")
print("=" * 80)

for cls, members in asset_classes.items():
    class_weight = sum(weights.get(m, 0) for m in members) * 100
    print(f"\n{cls}  (cluster total: {class_weight:.2f}%)")
    for inst in sorted(members, key=lambda x: -weights.get(x, 0)):
        w = weights.get(inst, 0) * 100
        v = vols.get(inst, 0) * 100
        print(f"  {inst:<14s}  vol={v:5.1f}%  weight={w:6.2f}%")

print("\n" + "=" * 80)
print("TOP 20 WEIGHTS")
print("=" * 80)
sorted_w = sorted(weights.items(), key=lambda kv: -kv[1])
for inst, w in sorted_w[:20]:
    cls = instrument_to_class.get(inst, "?")
    v = vols.get(inst, 0) * 100
    print(f"  {inst:<14s}  {cls:<18s}  vol={v:5.1f}%  {w*100:>6.2f}%")

print("\n" + "=" * 80)
print("BOTTOM 20 WEIGHTS")
print("=" * 80)
for inst, w in sorted_w[-20:]:
    cls = instrument_to_class.get(inst, "?")
    v = vols.get(inst, 0) * 100
    print(f"  {inst:<14s}  {cls:<18s}  vol={v:5.1f}%  {w*100:>6.2f}%")

print("\n" + "=" * 80)
print("DISPERSION")
print("=" * 80)
ws = [w*100 for w in weights.values()]
print(f"  Max: {max(ws):.2f}%  Min: {min(ws):.2f}%  Median: {np.median(ws):.2f}%")
print(f"  Near-zero (<0.5%): {sum(1 for w in ws if w < 0.5)}")
print(f"  Near-zero (<0.1%): {sum(1 for w in ws if w < 0.1)}")
