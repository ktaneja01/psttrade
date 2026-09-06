"""Build + visualize the handcraft_shrunk binary cluster tree for the LIVE
60-instrument universe (pulled from signals.py), using ENGINE-CONSISTENT
returns: diff(adjusted)/carry_price — NEVER pct_change on the adjusted level.

Highlights where the four softs (OJ, COFFEE, ROBUSTA, COCOA) land in the tree.
"""
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, to_tree
from scipy.spatial.distance import squareform

ADJ = "/usr/local/bc_data/futures_adjusted_prices/{}.parquet"
MULT = "/usr/local/bc_data/futures_multiple_prices/{}.parquet"

SOFTS = {"OJ", "COFFEE", "ROBUSTA", "COCOA"}

# --- pull the live universe + asset_classes from signals.py (pre-build seam) ---
src = open("signals.py").read().split("# Build system with dynamic optimisation")[0]
ns = {}
exec(src, ns)
asset_classes = ns["asset_classes"]
inst_to_class = {i: c for c, insts in asset_classes.items() for i in insts}
insts = [i for insts in asset_classes.values() for i in insts]
print(f"Building tree over {len(insts)} live instruments")


def engine_weekly(code):
    """Engine-consistent weekly returns: diff(adjusted)/carry_price."""
    adj = pd.read_parquet(ADJ.format(code)).squeeze().dropna()
    mult = pd.read_parquet(MULT.format(code))
    carry = mult["CARRY"].reindex(adj.index).ffill()
    # daily
    adj_d = adj.resample("1B").last()
    carry_d = carry.resample("1B").last().reindex(adj_d.index).ffill()
    ret = adj_d.diff() / carry_d.abs()
    ret = ret.replace([np.inf, -np.inf], np.nan).dropna()
    return ret.resample("W").sum().rename(code)


series = []
for i in insts:
    try:
        series.append(engine_weekly(i))
    except Exception as e:
        print(f"  skip {i}: {e}")
rets = pd.concat(series, axis=1)
rets = rets[rets.index >= "2016-01-01"].dropna(thresh=int(len(rets.columns) * 0.5)).fillna(0)
insts = list(rets.columns)
print(f"Tree on {len(insts)} instruments with usable returns\n")

# 50% shrinkage toward average off-diagonal correlation (handcraft_shrunk)
corr = rets.corr().values
n = corr.shape[0]
avg = corr[~np.eye(n, dtype=bool)].mean()
shrunk = 0.5 * corr + 0.5 * avg
np.fill_diagonal(shrunk, 1.0)
dist = np.sqrt(0.5 * (1 - shrunk))
np.fill_diagonal(dist, 0)

Z = linkage(squareform(dist, checks=False), method="ward")
tree, _ = to_tree(Z, rd=True)


def leaves_of(node):
    out = []
    def collect(n):
        if n.is_leaf():
            out.append(insts[n.id])
        else:
            collect(n.left); collect(n.right)
    collect(node)
    return out


def walk(node, weight, depth):
    if node.is_leaf():
        inst = insts[node.id]
        cls = inst_to_class.get(inst, "?")
        flag = "  <== SOFT" if inst in SOFTS else ""
        print(f"{'  ' * depth}|- {inst:<14} [{cls:<18}] {weight * 100:6.3f}%{flag}")
        return [(inst, weight, cls)]
    lv, rv = leaves_of(node.left), leaves_of(node.right)
    softs_here = [x for x in (lv + rv) if x in SOFTS]
    tag = f"  {{softs: {', '.join(softs_here)}}}" if softs_here else ""
    print(f"{'  ' * depth}* split n={len(lv) + len(rv)} w={weight * 100:.2f}%{tag}")
    res = walk(node.left, weight / 2, depth + 1)
    res += walk(node.right, weight / 2, depth + 1)
    return res


print("=" * 100)
print("HANDCRAFT_SHRUNK BINARY TREE — LIVE universe, engine-consistent returns")
print("=" * 100)
leaves = walk(tree, 1.0, 0)
print(f"\nTotal {sum(w for _, w, _ in leaves) * 100:.2f}%  Max {max(w for _, w, _ in leaves) * 100:.3f}%  Min {min(w for _, w, _ in leaves) * 100:.3f}%")

print("\n" + "=" * 60)
print("SOFTS placement (raw tree weight, pre 5% cap / redistribution)")
print("=" * 60)
for inst, w, cls in leaves:
    if inst in SOFTS:
        # find sibling leaves sharing its deepest branch
        print(f"  {inst:<10} raw-tree {w * 100:6.3f}%   class={cls}")

# Dendrogram
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.cluster.hierarchy import dendrogram

fig, ax = plt.subplots(figsize=(22, 10))
dendrogram(Z, labels=insts, leaf_rotation=90, leaf_font_size=8, ax=ax)
for lbl in ax.get_xticklabels():
    t = lbl.get_text()
    if t in SOFTS:
        lbl.set_color("red"); lbl.set_fontweight("bold")
ax.set_title("Handcraft_shrunk tree — LIVE 60, engine-consistent returns (softs in red)")
ax.set_ylabel(r"Distance $\sqrt{0.5(1-\rho_{shrunk})}$")
plt.tight_layout()
plt.savefig("/tmp/handcraft_tree_live.png", dpi=120)
print("\nDendrogram -> /tmp/handcraft_tree_live.png")
