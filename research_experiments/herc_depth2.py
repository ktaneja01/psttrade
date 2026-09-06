"""HERC (Hierarchical Equal Risk Contribution) at depth 2.

At each node of the dendrogram:
1. Split into 2 sub-clusters (hierarchical binary split)
2. Allocate equal risk between the two sub-clusters
3. Recurse within sub-cluster (up to specified depth)
4. Within deepest level, allocate inverse-vol (equal risk per instrument)

Depth 2 means: 2 top-level clusters each split into 2 sub-clusters = 4 "leaves"
The remaining instruments within each leaf get inverse-vol weights.
"""
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform

# Current universe — matches signals.py
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
instruments = [i for insts in asset_classes.values() for i in insts]
instrument_to_class = {i: c for c, insts in asset_classes.items() for i in insts}
print(f"Universe: {len(instruments)} instruments")

# Load returns
def daily_returns(code):
    path = f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet"
    df = pd.read_parquet(path)
    s = df.squeeze() if df.shape[1] == 1 else df.iloc[:, 0]
    s = s.dropna().resample("1B").last().ffill()
    s = s[s > 0]
    rets = s.pct_change().dropna()
    vol = rets.ewm(span=60).std() * np.sqrt(252)
    normed = rets / vol.shift(1).clip(lower=1e-4)
    normed.name = code
    return normed

returns_df = pd.concat([daily_returns(i) for i in instruments], axis=1)
returns_df = returns_df[returns_df.index >= "2016-01-01"].dropna(thresh=int(len(instruments) * 0.7)).fillna(0)
print(f"Returns matrix: {returns_df.shape}")

corr = returns_df.corr()
# Distance = sqrt(0.5 * (1 - corr))
dist_matrix = np.sqrt(0.5 * (1 - corr)).values
np.fill_diagonal(dist_matrix, 0)
Z = linkage(squareform(dist_matrix, checks=False), method="ward")


def herc_recursive(members: list, depth: int, max_depth: int, vols: dict) -> dict:
    """Recursive HERC allocation.
    At each depth, split members into 2 sub-clusters (via fcluster on their sub-distance matrix),
    split 50/50 between them, then recurse.
    At max_depth, inverse-vol weighting within cluster.
    """
    if len(members) == 1:
        return {members[0]: 1.0}
    if depth >= max_depth:
        # inverse-vol: each instrument gets weight ∝ 1/vol
        inv_vols = {m: 1.0 / max(vols[m], 1e-6) for m in members}
        total = sum(inv_vols.values())
        return {m: v / total for m, v in inv_vols.items()}

    # Split members into 2 sub-clusters using mini-hierarchical cluster
    sub_corr = corr.loc[members, members]
    sub_dist = np.sqrt(0.5 * (1 - sub_corr)).values
    np.fill_diagonal(sub_dist, 0)
    try:
        sub_Z = linkage(squareform(sub_dist, checks=False), method="ward")
        labels = fcluster(sub_Z, t=2, criterion="maxclust")
    except Exception:
        # trivial: inverse-vol fallback
        inv_vols = {m: 1.0 / max(vols[m], 1e-6) for m in members}
        total = sum(inv_vols.values())
        return {m: v / total for m, v in inv_vols.items()}

    sub1 = [m for m, lab in zip(members, labels) if lab == 1]
    sub2 = [m for m, lab in zip(members, labels) if lab == 2]
    if not sub1 or not sub2:
        inv_vols = {m: 1.0 / max(vols[m], 1e-6) for m in members}
        total = sum(inv_vols.values())
        return {m: v / total for m, v in inv_vols.items()}

    # 50/50 split between the 2 sub-clusters
    weights1 = herc_recursive(sub1, depth + 1, max_depth, vols)
    weights2 = herc_recursive(sub2, depth + 1, max_depth, vols)
    combined = {m: 0.5 * w for m, w in weights1.items()}
    combined.update({m: 0.5 * w for m, w in weights2.items()})
    return combined


# Compute vols (annualized % vol from last 500 days)
def compute_vol(code):
    path = f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet"
    s = pd.read_parquet(path).squeeze().dropna()
    s = s.resample("1B").last().ffill().tail(500)
    s = s[s > 0]
    return float(s.pct_change().dropna().std() * np.sqrt(252))

vols = {i: compute_vol(i) for i in instruments}

# Top-level split
print("\n" + "=" * 80)
print("DEPTH 1 — top-level split (2 clusters)")
print("=" * 80)
labels_d1 = fcluster(Z, t=2, criterion="maxclust")
d1_clusters = {}
for inst, lab in zip(instruments, labels_d1):
    d1_clusters.setdefault(f"T{lab}", []).append(inst)
for cid, members in d1_clusters.items():
    cls_hist = {}
    for m in members:
        c = instrument_to_class[m]
        cls_hist[c] = cls_hist.get(c, 0) + 1
    print(f"  {cid} (n={len(members)}): {', '.join(f'{c}:{n}' for c,n in cls_hist.items())}")
    print(f"    Members: {', '.join(members[:15])}{'...' if len(members)>15 else ''}")

# Depth 2 split
print("\n" + "=" * 80)
print("DEPTH 2 — each top cluster split into 2 sub-clusters (4 total)")
print("=" * 80)
d2_result = {}
for cid, members in d1_clusters.items():
    if len(members) <= 1:
        d2_result[f"{cid}.1"] = members
        continue
    sub_corr = corr.loc[members, members]
    sub_dist = np.sqrt(0.5 * (1 - sub_corr)).values
    np.fill_diagonal(sub_dist, 0)
    sub_Z = linkage(squareform(sub_dist, checks=False), method="ward")
    sub_labels = fcluster(sub_Z, t=2, criterion="maxclust")
    for inst, lab in zip(members, sub_labels):
        d2_result.setdefault(f"{cid}.{lab}", []).append(inst)

for cid, members in sorted(d2_result.items()):
    cls_hist = {}
    for m in members:
        c = instrument_to_class[m]
        cls_hist[c] = cls_hist.get(c, 0) + 1
    print(f"\n  {cid} (n={len(members)}):  {', '.join(f'{c}:{n}' for c,n in cls_hist.items())}")
    print(f"    {', '.join(members)}")

# Inter-cluster correlations
print("\n" + "=" * 80)
print("INTER-CLUSTER AVERAGE CORRELATIONS (depth 2)")
print("=" * 80)
cluster_names = sorted(d2_result.keys())
print(f"\n{'':>8s}", end="")
for c in cluster_names:
    print(f"{c:>9s}", end="")
print()
for c1 in cluster_names:
    print(f"{c1:>8s}", end="")
    for c2 in cluster_names:
        m1, m2 = d2_result[c1], d2_result[c2]
        if c1 == c2 and len(m1) > 1:
            # intra: avg of off-diagonal
            sub = corr.loc[m1, m1]
            mask = ~np.eye(len(m1), dtype=bool)
            v = sub.values[mask].mean()
        elif c1 == c2:
            v = 1.0
        else:
            v = corr.loc[m1, m2].values.mean()
        print(f"{v:>+9.3f}", end="")
    print()

# Also distance (sqrt(0.5*(1-corr)))
print("\n\nDISTANCE MATRIX (√(½(1−corr)))")
print(f"{'':>8s}", end="")
for c in cluster_names:
    print(f"{c:>9s}", end="")
print()
for c1 in cluster_names:
    print(f"{c1:>8s}", end="")
    for c2 in cluster_names:
        m1, m2 = d2_result[c1], d2_result[c2]
        if c1 == c2 and len(m1) > 1:
            sub = corr.loc[m1, m1]
            mask = ~np.eye(len(m1), dtype=bool)
            avg_c = sub.values[mask].mean()
            d = np.sqrt(0.5 * (1 - avg_c))
        elif c1 == c2:
            d = 0.0
        else:
            avg_c = corr.loc[m1, m2].values.mean()
            d = np.sqrt(0.5 * (1 - avg_c))
        print(f"{d:>9.3f}", end="")
    print()

# HERC weights at depth 2
print("\n\n" + "=" * 80)
print("HERC WEIGHTS at depth 2 (equal-risk split at each node)")
print("=" * 80)
weights = herc_recursive(instruments, depth=0, max_depth=2, vols=vols)
# Group by depth-2 cluster for display
for cid, members in sorted(d2_result.items()):
    cluster_total = sum(weights[m] for m in members)
    print(f"\n{cid}  (total weight: {cluster_total*100:.2f}%, n={len(members)})")
    for m in sorted(members, key=lambda x: -weights[x]):
        print(f"  {m:<14s}  vol={vols[m]*100:5.1f}%  weight={weights[m]*100:5.2f}%")

print(f"\nTotal weight sum: {sum(weights.values())*100:.2f}%")
