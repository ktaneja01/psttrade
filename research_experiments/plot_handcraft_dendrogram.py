"""Plot dendrogram of the 55-instrument universe using SHRUNK correlations
(what handcraft_shrunk actually sees when building the binary cluster tree).
"""
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, dendrogram
from scipy.spatial.distance import squareform
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

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

CLASS_COLORS = {
    "Bonds":            "#1f77b4",  # blue
    "Grains":           "#8c564b",  # brown
    "Energy-Livestock": "#ff7f0e",  # orange
    "Equity-Risk":      "#2ca02c",  # green
    "G10-FX":           "#9467bd",  # purple
    "EM-Metal-Crypto":  "#e377c2",  # pink
}

def daily_returns(code):
    s = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").squeeze()
    s = s.dropna().resample("1B").last().ffill()
    s = s[s > 0]
    return s.pct_change().dropna().rename(code)

returns_df = pd.concat([daily_returns(i) for i in instruments], axis=1)
returns_df = returns_df[returns_df.index >= "2016-01-01"].dropna(thresh=int(N * 0.5)).fillna(0)
weekly = returns_df.resample("W").sum()
corr = weekly.corr()

# Apply correlation shrinkage (same as handcraft_shrunk)
avg_corr = corr.values[~np.eye(N, dtype=bool)].mean()
shrunk = 0.5 * corr.values + 0.5 * avg_corr
np.fill_diagonal(shrunk, 1.0)
print(f"Avg correlation: {avg_corr:.3f} (shrinking 50% toward this)")

# Distance = sqrt(0.5*(1-corr))
dist = np.sqrt(0.5 * (1 - shrunk))
np.fill_diagonal(dist, 0)

# Ward linkage
Z = linkage(squareform(dist, checks=False), method="ward")

# Plot dendrogram with color-coded leaf labels
fig, ax = plt.subplots(figsize=(22, 10))
dgram = dendrogram(
    Z,
    labels=instruments,
    leaf_rotation=90,
    leaf_font_size=9,
    ax=ax,
)

# Color the labels by asset class
for lbl in ax.get_xticklabels():
    text = lbl.get_text()
    cls = instrument_to_class.get(text, "?")
    lbl.set_color(CLASS_COLORS.get(cls, "black"))

# Legend
import matplotlib.patches as mpatches
handles = [mpatches.Patch(color=c, label=cls) for cls, c in CLASS_COLORS.items()]
ax.legend(handles=handles, loc="upper right", fontsize=10)

ax.set_title(
    f"Hierarchical clustering — 55 instruments (Ward linkage on shrunk correlation distance)\n"
    f"shrinkage_corr=0.5, leaves colored by manual asset class",
    fontsize=12,
)
ax.set_ylabel("Distance  √(½ × (1 − shrunk_corr))")
ax.axhline(y=1.0, color="gray", linestyle="--", alpha=0.5, label="K=3 cut")
ax.axhline(y=1.2, color="gray", linestyle=":", alpha=0.5)

plt.tight_layout()
plt.savefig("/tmp/handcraft_dendrogram.png", dpi=120, bbox_inches="tight")
print("\nSaved to /tmp/handcraft_dendrogram.png")

# Also print the cluster tree structure
from scipy.cluster.hierarchy import fcluster
print("\nCluster tree at various K:")
for K in [2, 3, 4, 5, 6, 7]:
    labels = fcluster(Z, t=K, criterion="maxclust")
    print(f"\n  --- K = {K} ---")
    clusters = {}
    for inst, lab in zip(instruments, labels):
        clusters.setdefault(lab, []).append(inst)
    for cid in sorted(clusters):
        members = clusters[cid]
        cls_hist = {}
        for m in members:
            cls_hist[instrument_to_class[m]] = cls_hist.get(instrument_to_class[m], 0) + 1
        print(f"    Cluster {cid} (n={len(members):2d}):  "
              f"{', '.join(f'{c}:{n}' for c, n in sorted(cls_hist.items(), key=lambda x: -x[1]))}")
