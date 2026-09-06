"""Dendrogram of the live 68-instrument book using the SAME clustering handcraft
uses internally: complete linkage on pdist(shrunk_correlation). Leaves labelled
with frozen weight % and colored by asset class. Reproduces the tree that the
handcraft correlation-clustering built the FROZEN weights from.
"""
import io, sys, re
import numpy as np, pandas as pd
from scipy.cluster import hierarchy as sch
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

# live universe + weights + classes from signals.py
src = open("signals.py").read().split("# Build system with dynamic")[0]
ns = {}; o = sys.stdout; sys.stdout = io.StringIO(); exec(src, ns); sys.stdout = o
fw = ns["FROZEN_HANDCRAFT_SHRUNK_WEIGHTS"]
ac = ns["asset_classes"]
i2c = {i: c for c, insts in ac.items() for i in insts}
insts = list(fw.keys())

# engine-consistent weekly returns (diff/carry), 2016+, matching freeze script
def eret(code):
    adj = pd.to_numeric(pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").iloc[:,0], errors="coerce").dropna().resample("1B").last()
    carry = pd.to_numeric(pd.read_parquet(f"/usr/local/bc_data/futures_multiple_prices/{code}.parquet")["PRICE"], errors="coerce").resample("1B").last().reindex(adj.index).ffill()
    return (adj.diff()/carry.abs()).replace([np.inf,-np.inf],np.nan).rename(code)

R = pd.concat([eret(i) for i in insts], axis=1)
R = R[R.index >= "2016-01-01"].resample("W").sum().fillna(0)
R = R.loc[:, R.std() > 1e-12]
insts = list(R.columns); n = len(insts)

# shrunk correlation (handcraft: 50% toward average off-diagonal)
C = R.corr().values
avg = C[~np.eye(n, dtype=bool)].mean()
S = 0.5*C + 0.5*avg; np.fill_diagonal(S, 1.0)

# EXACT handcraft clustering: complete linkage on pdist of the correlation rows
d = sch.distance.pdist(S)
L = sch.linkage(d, method="complete")

# class -> color
classes = sorted(set(i2c.get(i, "?") for i in insts))
cmap = plt.get_cmap("tab10")
ccol = {c: cmap(k % 10) for k, c in enumerate(classes)}
labels = [f"{i}  {fw.get(i,0)*100:.1f}%" for i in insts]

fig, ax = plt.subplots(figsize=(14, 18))
dn = sch.dendrogram(L, labels=labels, orientation="left", ax=ax,
                    color_threshold=0.7*max(L[:,2]), leaf_font_size=8)
# color leaf labels by asset class
ylbls = ax.get_ymajorticklabels()
for lbl in ylbls:
    code = lbl.get_text().split()[0]
    lbl.set_color(ccol.get(i2c.get(code, "?"), "black"))
# legend
from matplotlib.patches import Patch
ax.legend(handles=[Patch(color=ccol[c], label=c) for c in classes],
          loc="lower right", fontsize=9, title="asset class")
ax.set_title(f"Handcraft correlation-cluster dendrogram — {n} instruments\n"
             f"(complete linkage on 50%-shrunk correlation; leaf = frozen weight %)", fontsize=11)
ax.set_xlabel("cluster distance (complete linkage)")
plt.tight_layout(); plt.savefig("/tmp/dendro_weights.png", dpi=110)
print(f"Saved /tmp/dendro_weights.png  ({n} instruments)")

# also print the top-level cluster structure as text
print("\n=== Top clusters at cut giving ~8 groups (correlation tree) ===")
for K in [6, 8, 10]:
    ind = sch.fcluster(L, K, criterion="maxclust")
    groups = {}
    for i, g in zip(insts, ind): groups.setdefault(g, []).append(i)
    print(f"\n--- K={K} clusters ---")
    for g, mem in sorted(groups.items(), key=lambda x: -sum(fw.get(m,0) for m in x[1])):
        wsum = sum(fw.get(m,0) for m in mem)*100
        from collections import Counter
        cc = Counter(i2c.get(m,"?") for m in mem)
        dom = ", ".join(f"{v}{k[:4]}" for k,v in cc.most_common(3))
        print(f"  [{wsum:4.1f}%] n={len(mem):2d} ({dom}): {', '.join(sorted(mem))}")
