"""Compute weights for all 4 pysystemtrade optimisers offline + run full backtests."""
import numpy as np
import pandas as pd
from sysquant.estimators.estimates import Estimates
from sysquant.estimators.correlations import correlationEstimate
from sysquant.estimators.mean_estimator import meanEstimates
from sysquant.estimators.stdev_estimator import stdevEstimates
from sysquant.optimisation.optimisers.call_optimiser import REGISTER_OF_OPTIMISERS

# Universe
asset_classes = {
    "Bonds": ["US10", "US10U", "US20", "US30", "BUND", "GILT"],
    "Grains": ["REDWHEAT", "SOYMEAL", "SOYOIL", "WHEAT", "CORN", "SOYBEAN"],
    "Energy-Livestock": ["CRUDE_W", "GAS_US", "GASOILINE", "HEATOIL", "GAS-LAST",
                         "LIVECOW", "FEEDCOW", "LEANHOG", "RICE", "GBPJPY",
                         "COFFEE", "OJ", "GASOIL"],
    "Equity-Risk": ["SP500", "NASDAQ", "RUSSELL", "DOW", "NIKKEI", "SP400",
                    "CAC", "DAX", "EUROSTX", "FTSE100", "VIX", "V2X"],
    "G10-FX": ["EUR", "JPY", "GBP", "AUD", "NZD", "CHF", "PLN", "EURCAD"],
    "EM-Metal-Crypto": ["MXP", "ZAR", "BRE", "GOLD", "SILVER", "COPPER", "PLAT", "PALLAD",
                        "BITCOIN", "ETHEREUM"],
}
instruments = [i for insts in asset_classes.values() for i in insts]
instrument_to_class = {i: c for c, insts in asset_classes.items() for i in insts}

# Load returns
def daily_returns(code):
    s = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").squeeze()
    s = s.dropna().resample("1B").last().ffill()
    s = s[s > 0]
    return s.pct_change().dropna().rename(code)

returns_df = pd.concat([daily_returns(i) for i in instruments], axis=1)
returns_df = returns_df[returns_df.index >= "2016-01-01"].dropna(thresh=int(len(instruments) * 0.5)).fillna(0)
weekly = returns_df.resample("W").sum()

corr = correlationEstimate(weekly.corr(), list(weekly.columns))
estimates = Estimates(
    correlation=corr,
    mean=meanEstimates(dict(weekly.mean() * 52)),
    stdev=stdevEstimates(dict(weekly.std() * np.sqrt(52))),
    data_length=len(weekly), frequency="W",
)

# Compute weights via each method
print("=" * 90)
print("WEIGHTS PER OPTIMIZER (sum normalized to 100%)")
print("=" * 90)
print(f"{'Cluster':>18s}  {'1/N':>10s}  {'shrinkage':>10s}  {'handcraft':>10s}  {'one_period':>11s}")

all_results = {}
for name in ["equal_weights", "shrinkage", "handcraft", "one_period"]:
    try:
        result = REGISTER_OF_OPTIMISERS[name](estimates, equalise_SR=True, equalise_vols=True)
        w = dict(result.weights)
        # Normalize
        tot = sum(abs(v) for v in w.values()) or 1.0
        w = {k: v/tot for k, v in w.items()}
        all_results[name] = w
    except Exception as e:
        print(f"  {name}: FAILED - {str(e)[:60]}")
        all_results[name] = None

# Cluster-level weights
for cls, members in asset_classes.items():
    row = f"{cls:>18s}"
    for name in ["equal_weights", "shrinkage", "handcraft", "one_period"]:
        w = all_results.get(name)
        if w is None:
            row += f"  {'ERR':>10s}" if name != "one_period" else f"  {'ERR':>11s}"
            continue
        cls_total = sum(w.get(m, 0) for m in members) * 100
        if name == "one_period":
            row += f"  {cls_total:>+10.2f}%"
        else:
            row += f"  {cls_total:>+9.2f}%"
    print(row)

# Top-5 and bottom-5 per method
for name, weights in all_results.items():
    if weights is None:
        continue
    print(f"\n{name.upper()} — top 10 weights:")
    for inst, w in sorted(weights.items(), key=lambda kv: -abs(kv[1]))[:10]:
        cls = instrument_to_class.get(inst, "?")
        print(f"  {inst:<14s}  {cls:<18s}  {w*100:>+7.2f}%")

    # Dispersion metrics
    abs_w = [abs(v) for v in weights.values()]
    print(f"\n{name.upper()} — dispersion:")
    print(f"  max: {max(abs_w)*100:+.2f}%, min: {min(abs_w)*100:+.3f}%, std: {np.std(list(weights.values()))*100:.2f}%")
    print(f"  negative weights: {sum(1 for v in weights.values() if v < -0.001)}")
    print(f"  near-zero (<0.1%): {sum(1 for v in abs_w if v < 0.001)}")
