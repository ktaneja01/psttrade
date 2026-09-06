"""HERC (Hierarchical Equal Risk Contribution) at K=7 with shrunk correlations.

Algorithm:
1. Compute correlation matrix, shrink 50% toward average
2. Build Ward hierarchical tree on shrunk correlation distance
3. Cut at K=7 clusters
4. Each cluster gets 1/7 of total risk budget (equal-risk across clusters)
5. Within each cluster: inverse-variance weights (equal risk per instrument)

Writes weights out as Python dict for pasting into signals.py.
"""
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform

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
N = len(instruments)

def daily_returns(code):
    s = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").squeeze()
    s = s.dropna().resample("1B").last().ffill()
    s = s[s > 0]
    return s.pct_change().dropna().rename(code)

returns_df = pd.concat([daily_returns(i) for i in instruments], axis=1)
returns_df = returns_df[returns_df.index >= "2016-01-01"].dropna(thresh=int(N * 0.5)).fillna(0)
weekly = returns_df.resample("W").sum()

# Shrunk correlations
corr = weekly.corr().values
np.fill_diagonal(corr, 1.0)
avg_corr = corr[~np.eye(N, dtype=bool)].mean()
shrunk = 0.5 * corr + 0.5 * avg_corr
np.fill_diagonal(shrunk, 1.0)
print(f"Avg correlation: {avg_corr:.3f} (shrunk 50% toward this)")

# Hierarchical tree on shrunk correlation distance
dist = np.sqrt(0.5 * (1 - shrunk))
np.fill_diagonal(dist, 0)
Z = linkage(squareform(dist, checks=False), method="ward")

# ============================================================
# HERC — cut at K=7
# ============================================================
K = 4
labels = fcluster(Z, t=K, criterion="maxclust")

# Vols (annualized)
vols = np.array([float(weekly[i].std() * np.sqrt(52)) for i in instruments])
# Guard against vol blow-up from back-adjusted-price issues
vols_clean = np.clip(vols, 0.01, 2.0)  # clip to 1-200% annual vol

# Build clusters
clusters = {}
for i, (inst, lab) in enumerate(zip(instruments, labels)):
    clusters.setdefault(lab, []).append((inst, i))

print(f"\nHERC at K={K} — cluster structure:")
for cid in sorted(clusters):
    members = clusters[cid]
    cls_hist = {}
    for m, _ in members:
        cls_hist[instrument_to_class[m]] = cls_hist.get(instrument_to_class[m], 0) + 1
    print(f"  Cluster {cid} (n={len(members):2d}):  "
          f"{', '.join(f'{c}:{n}' for c, n in sorted(cls_hist.items(), key=lambda x: -x[1]))}")

# HERC weights:
# Each cluster gets 1/K risk budget.
# Within cluster, inverse-variance weights (weight ∝ 1/vol²) for equal risk contribution.
weights = {}
cluster_budget = 1.0 / K
for cid, members in clusters.items():
    names = [m[0] for m in members]
    idxs = [m[1] for m in members]
    inv_var = 1.0 / vols_clean[idxs]**2  # inverse variance
    inv_var_normed = inv_var / inv_var.sum()
    for j, name in enumerate(names):
        weights[name] = cluster_budget * inv_var_normed[j]

# Normalize (should already be 1.0, but cover floating pt)
total = sum(weights.values())
weights = {k: v/total for k, v in weights.items()}

# Apply 5% cap (redistribute excess within cluster)
MAX_W = 0.05
iterations = 0
while iterations < 10:
    capped_any = False
    for cid, members in clusters.items():
        names = [m[0] for m in members]
        cluster_total = sum(weights[n] for n in names)
        over = {n: weights[n] for n in names if weights[n] > MAX_W}
        if not over:
            continue
        under = {n: weights[n] for n in names if weights[n] <= MAX_W}
        if not under:
            continue
        excess = sum(weights[n] - MAX_W for n in over)
        for n in over:
            weights[n] = MAX_W
            capped_any = True
        under_total = sum(weights[n] for n in under)
        for n in under:
            weights[n] += excess * (weights[n] / under_total) if under_total > 0 else 0
    if not capped_any:
        break
    iterations += 1

# Report
print(f"\n{'=' * 80}")
print(f"HERC K={K} weights (shrunk correlations, inverse-variance within cluster)")
print(f"{'=' * 80}")

# Map cluster id back to manual class coverage for readability
for cid in sorted(clusters):
    members = clusters[cid]
    names = [m[0] for m in members]
    class_tally = sorted({instrument_to_class[n] for n in names})
    cluster_weight = sum(weights[n] for n in names) * 100
    print(f"\nCluster {cid} (n={len(names)}, total={cluster_weight:.2f}%)  [{', '.join(class_tally)}]")
    for n in sorted(names, key=lambda x: -weights[x]):
        w = weights[n] * 100
        v = vols[instruments.index(n)] * 100
        cls = instrument_to_class[n]
        print(f"  {n:<14s}  class={cls:<18s}  vol={v:5.1f}%  weight={w:>5.2f}%")

print(f"\nTotal weight: {sum(weights.values())*100:.2f}%")
print(f"Max weight: {max(weights.values())*100:.2f}%")
print(f"Min weight: {min(weights.values())*100:.3f}%")

# Output as Python dict
print(f"\n{'=' * 80}")
print("Weights as Python dict (paste into signals.py):")
print(f"{'=' * 80}")
print("HERC_K7_WEIGHTS = {")
for n in sorted(weights, key=lambda x: -weights[x]):
    print(f'    "{n}": {weights[n]:.6f},')
print("}")
