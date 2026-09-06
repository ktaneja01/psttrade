"""Hierarchical clustering of our 37-instrument universe.

Compute correlation matrix of daily returns, build a correlation-based
distance tree, and report cluster composition at various thresholds.
Uses Ward linkage (standard for hierarchical equal risk).
"""
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster, dendrogram
from scipy.spatial.distance import squareform

# Current universe (51 instruments — matches signals.py after bad_markets filter)
asset_classes = {
    "Bonds":            ["US10", "US10U", "US20", "US30", "BUND", "GILT"],
    "Grains":           ["REDWHEAT", "SOYMEAL", "SOYOIL", "WHEAT", "CORN", "SOYBEAN"],
    "Energy-Livestock": ["CRUDE_W", "GAS_US", "GASOILINE", "HEATOIL", "GAS-LAST",
                         "LIVECOW", "FEEDCOW", "LEANHOG", "RICE", "GBPJPY",
                         "COFFEE", "GASOIL"],
    "Equity-Risk":      ["SP500", "NASDAQ", "RUSSELL", "DOW", "NIKKEI", "SP400",
                         "VIX", "V2X"],
    "G10-FX":           ["EUR", "JPY", "GBP", "AUD", "NZD", "CHF", "PLN", "EURCAD"],
    "EM-Metal-Crypto":  ["MXP", "ZAR", "BRE", "GOLD", "SILVER", "COPPER", "PLAT", "PALLAD",
                         "BITCOIN", "ETHEREUM"],
}
instrument_to_class = {i: c for c, insts in asset_classes.items() for i in insts}
instruments = [i for insts in asset_classes.values() for i in insts]
print(f"Universe: {len(instruments)} instruments across {len(asset_classes)} classes")

# ==========================================================
# Load daily returns
# ==========================================================
def daily_returns(code):
    path = f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet"
    df = pd.read_parquet(path)
    s = df.squeeze() if df.shape[1] == 1 else df.iloc[:, 0]
    s = s.dropna().resample("1B").last().ffill()
    s = s[s > 0]
    # Vol-normalize returns so big movers and small movers get equal weight
    rets = s.pct_change().dropna()
    vol = rets.ewm(span=60).std() * np.sqrt(252)
    # Use log returns normalized by trailing vol (unit-variance)
    normed = rets / vol.shift(1).clip(lower=1e-4)
    normed.name = code
    return normed

print("\nLoading returns...")
returns_df = pd.concat([daily_returns(i) for i in instruments], axis=1)
returns_df = returns_df[returns_df.index >= "2016-01-01"]
# Only use dates where most instruments have data
returns_df = returns_df.dropna(thresh=int(len(instruments) * 0.7))
returns_df = returns_df.fillna(0)  # fill remaining gaps with zero (treat as no return)
print(f"Return matrix: {returns_df.shape}")

# ==========================================================
# Correlation -> distance
# ==========================================================
corr = returns_df.corr()
# Distance: sqrt(0.5 * (1 - corr)) — a standard metric
dist = np.sqrt(0.5 * (1 - corr)).values
# Convert to condensed distance for linkage
np.fill_diagonal(dist, 0)
condensed = squareform(dist, checks=False)

# ==========================================================
# Ward linkage
# ==========================================================
Z = linkage(condensed, method="ward")

# ==========================================================
# Report cluster composition at multiple thresholds
# ==========================================================
print("\n" + "=" * 70)
print("Cluster composition at different K values")
print("=" * 70)

for K in [2, 3, 4, 5, 6, 7, 8, 10]:
    labels = fcluster(Z, t=K, criterion="maxclust")
    clusters = {}
    for inst, lab in zip(instruments, labels):
        clusters.setdefault(lab, []).append(inst)
    actual_K = len(clusters)
    print(f"\n--- K = {K} (got {actual_K} clusters) ---")
    for cid, members in sorted(clusters.items()):
        # Count asset-class breakdown
        class_counts = {}
        for m in members:
            c = instrument_to_class.get(m, "?")
            class_counts[c] = class_counts.get(c, 0) + 1
        class_str = ", ".join(f"{c}:{n}" for c, n in sorted(class_counts.items(), key=lambda x: -x[1]))
        print(f"  Cluster {cid} (n={len(members)}): {class_str}")
        print(f"    {', '.join(members)}")

# ==========================================================
# Optimal K via "gap" or elbow in linkage distances
# ==========================================================
print("\n" + "=" * 70)
print("Linkage merge distances (find the 'elbow')")
print("=" * 70)
# Z[:, 2] is the distance at each merge step; large jumps = natural cluster boundary
merge_dists = Z[:, 2]
print(f"\n{'Step':>5s} {'Merge distance':>15s} {'Clusters remaining':>20s}")
n = len(instruments)
for i, d in enumerate(merge_dists):
    remaining = n - i - 1
    if remaining <= 15:  # only show last 15 merges
        jump = "<-- BIG JUMP" if i > 0 and d > 1.3 * merge_dists[i-1] else ""
        print(f"{i:>5d} {d:>15.3f} {remaining:>20d}  {jump}")

# ==========================================================
# Within- vs across-class correlation diagnostic
# ==========================================================
print("\n" + "=" * 70)
print("Within-class vs across-class avg correlation")
print("=" * 70)
within_corrs = []
across_corrs = []
for i, a in enumerate(instruments):
    for b in instruments[i+1:]:
        c = corr.loc[a, b]
        if np.isnan(c):
            continue
        if instrument_to_class[a] == instrument_to_class[b]:
            within_corrs.append(c)
        else:
            across_corrs.append(c)
print(f"Within-class avg corr:  {np.mean(within_corrs):+.3f}  (n={len(within_corrs)})")
print(f"Across-class avg corr:  {np.mean(across_corrs):+.3f}  (n={len(across_corrs)})")
print(f"Diagnostic: within > across → classes are meaningful. Bigger gap → cleaner structure.")

# ==========================================================
# Dendrogram plot
# ==========================================================
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(18, 8))
dendrogram(Z, labels=instruments, leaf_rotation=90, leaf_font_size=9, ax=ax)
ax.set_title("Hierarchical clustering of 37 instruments (Ward linkage on correlation distance)")
ax.set_ylabel("Distance (√(0.5 × (1 − corr)))")
plt.tight_layout()
plt.savefig("/tmp/dendrogram.png", dpi=100)
print("\nDendrogram saved to /tmp/dendrogram.png")
