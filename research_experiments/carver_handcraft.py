"""Run Carver's handcraft portfolio optimization on our 55-instrument universe.

Uses pysystemtrade's handcraft_optimisation (the same function that runs when
use_instrument_weight_estimates=True). Shows the cluster hierarchy + weights.
"""
import numpy as np
import pandas as pd
from sysquant.estimators.estimates import Estimates
from sysquant.estimators.correlations import correlationEstimate
from sysquant.estimators.mean_estimator import meanEstimates
from sysquant.estimators.stdev_estimator import stdevEstimates
from sysquant.optimisation.optimisers.handcraft import (
    handcraftPortfolio, handcraft_optimisation,
    create_sub_portfolios_from_portfolio,
)

# Current universe (51 tradeable instruments after bad_markets + 4 EU equities = 55)
# Matches signals.py asset_classes after bad_markets filter.
asset_classes = {
    "Bonds":            ["US10", "US10U", "US20", "US30", "BUND", "GILT"],
    "Grains":           ["REDWHEAT", "SOYMEAL", "SOYOIL", "WHEAT", "CORN", "SOYBEAN"],
    "Energy-Livestock": ["CRUDE_W", "GAS_US", "GASOILINE", "HEATOIL", "GAS-LAST",
                         "LIVECOW", "FEEDCOW", "LEANHOG", "RICE", "GBPJPY",
                         "COFFEE", "OJ", "GASOIL"],
    "Equity-Risk":      ["SP500", "NASDAQ", "RUSSELL", "DOW", "NIKKEI", "SP400",
                         "CAC", "DAX", "EUROSTX", "FTSE100",
                         "VIX", "V2X"],
    "G10-FX":           ["EUR", "JPY", "GBP", "AUD", "NZD", "CHF", "PLN", "EURCAD"],
    "EM-Metal-Crypto":  ["MXP", "ZAR", "BRE", "GOLD", "SILVER", "COPPER", "PLAT", "PALLAD",
                         "BITCOIN", "ETHEREUM"],
}
instruments = [i for insts in asset_classes.values() for i in insts]
instrument_to_class = {i: c for c, insts in asset_classes.items() for i in insts}
print(f"Universe: {len(instruments)} instruments")

# Load daily returns
def daily_returns(code):
    path = f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet"
    df = pd.read_parquet(path)
    s = df.squeeze() if df.shape[1] == 1 else df.iloc[:, 0]
    s = s.dropna().resample("1B").last().ffill()
    s = s[s > 0]
    return s.pct_change().dropna().rename(code)

print("Loading returns...")
returns_df = pd.concat([daily_returns(i) for i in instruments], axis=1)
returns_df = returns_df[returns_df.index >= "2016-01-01"].dropna(thresh=int(len(instruments) * 0.5)).fillna(0)
print(f"Returns matrix: {returns_df.shape}")

# Build Estimates (correlation + mean + stdev, weekly frequency)
weekly = returns_df.resample("W").sum()
corr_matrix_df = weekly.corr()
corr = correlationEstimate(corr_matrix_df, list(corr_matrix_df.columns))

# Annualized means and stdevs
mean_annual = weekly.mean() * 52
stdev_annual = weekly.std() * np.sqrt(52)
mean = meanEstimates(dict(mean_annual))
stdev = stdevEstimates(dict(stdev_annual))

estimates = Estimates(
    correlation=corr, mean=mean, stdev=stdev,
    data_length=len(weekly), frequency="W",
)
print(f"Data length: {estimates.data_length_years:.1f} years")

# Run Carver's handcraft
print("\n" + "=" * 70)
print("Running Carver's handcraft optimisation...")
print("=" * 70)
result = handcraft_optimisation(estimates, equalise_SR=True, equalise_vols=True)
weights = result.weights

# Show the cluster hierarchy by recursively splitting
def show_hierarchy(portfolio: handcraftPortfolio, depth=0, label="Root"):
    """Recursively show the binary cluster tree."""
    assets = list(portfolio.correlation.columns)
    indent = "  " * depth
    if len(assets) == 1:
        print(f"{indent}└─ {label} [{assets[0]}]")
        return

    sub_portfolios = create_sub_portfolios_from_portfolio(portfolio)
    print(f"{indent}├─ {label} (n={len(assets)})")
    for i, sub in enumerate(sub_portfolios):
        sub_label = f"{label}.{i+1}"
        show_hierarchy(sub, depth + 1, sub_label)

print("\nCluster hierarchy (binary tree):")
root = handcraftPortfolio(estimates)
try:
    show_hierarchy(root, depth=0, label="Root")
except RecursionError:
    print("  (too deep to display)")
except Exception as e:
    print(f"  error displaying hierarchy: {e}")

# Show weights grouped by our manual asset class for comparison
print("\n" + "=" * 70)
print("HANDCRAFT WEIGHTS by manual class")
print("=" * 70)

for cls, members in asset_classes.items():
    class_weight = sum(weights.get(m, 0) for m in members)
    print(f"\n{cls}  (class total: {class_weight*100:.2f}%)")
    for inst in sorted(members, key=lambda x: -weights.get(x, 0)):
        if inst in weights:
            w = weights[inst]
            print(f"  {inst:<14s}  {w*100:>6.2f}%")

# Also show in one table sorted by weight
print("\n" + "=" * 70)
print("TOP 20 weights")
print("=" * 70)
sorted_weights = sorted(dict(weights).items(), key=lambda kv: -kv[1])
for inst, w in sorted_weights[:20]:
    cls = instrument_to_class.get(inst, "?")
    print(f"  {inst:<14s}  {cls:<18s}  {w*100:>6.2f}%")

print("\n" + "=" * 70)
print("BOTTOM 20 weights")
print("=" * 70)
for inst, w in sorted_weights[-20:]:
    cls = instrument_to_class.get(inst, "?")
    print(f"  {inst:<14s}  {cls:<18s}  {w*100:>6.2f}%")

print(f"\nTotal weight: {sum(weights.values())*100:.2f}%")
