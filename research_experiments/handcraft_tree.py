"""Build and visualize the handcraft_shrunk binary cluster tree.
Shows how weights cascade from 100% at the root down to each leaf.
"""
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster, to_tree
from scipy.spatial.distance import squareform

bad = {'US2','US3','US5','EURCHF','GBPEUR','CAD','SOFR1','LUMBER-new','OATIES','STEEL',
       'BRENT_W','SHATZ','BOBL','COTTON2','SUGAR11','EURIBOR','BTP3','BRENT-LAST','INR',
       'US10U','US20','CAC','DAX','GAS_US','OAT','BUXL','BONO'}
raw = {
    'Bonds': ['US10','US30','BUND','GILT','BTP'],
    'Grains': ['REDWHEAT','SOYMEAL','SOYOIL','WHEAT','CORN','SOYBEAN'],
    'Energy-Livestock': ['CRUDE_W','GASOILINE','HEATOIL','GAS-LAST','LIVECOW','FEEDCOW','LEANHOG','RICE','GBPJPY','COFFEE','OJ','GASOIL','COCOA'],
    'Equity-Risk': ['SP500','NASDAQ','RUSSELL','DOW','NIKKEI','SP400','EUROSTX','FTSE100','VIX','V2X','AEX','HANG','SMI','MSCIWORLD'],
    'G10-FX': ['EUR','JPY','GBP','AUD','NZD','CHF','PLN','EURCAD','DX','NOK','SEK'],
    'EM-Metal-Crypto': ['MXP','ZAR','BRE','GOLD','SILVER','COPPER','PLAT','PALLAD','BITCOIN','ETHEREUM'],
}
insts = [i for vs in raw.values() for i in vs]
print(f"Building tree over {len(insts)} instruments")

def wkly(c):
    s = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{c}.parquet").squeeze().dropna()
    s = s.resample("1B").last().ffill(); s = s[s>0]
    r = s.pct_change().dropna().replace([np.inf,-np.inf], np.nan).dropna()
    return r.resample("W").sum().rename(c)

rets = pd.concat([wkly(i) for i in insts], axis=1)
rets = rets[rets.index >= "2016-01-01"].dropna(thresh=int(len(insts)*0.5)).fillna(0)

# 50% shrinkage toward average correlation
corr = rets.corr().values
n = corr.shape[0]
avg = corr[~np.eye(n, dtype=bool)].mean()
shrunk = 0.5*corr + 0.5*avg
np.fill_diagonal(shrunk, 1.0)
dist = np.sqrt(0.5*(1 - shrunk))
np.fill_diagonal(dist, 0)

# Ward linkage — same method handcraft uses for clustering
Z = linkage(squareform(dist, checks=False), method='ward')
tree = to_tree(Z, rd=True)
root = tree[0]

inst_to_class = {i: c for c, vs in raw.items() for i in vs}

def walk(node, weight, depth, parent_label=None):
    """Recurse the binary tree, printing weight at each level.
    Under equalise_vols=True, weight splits 50/50 at each internal node."""
    if node.is_leaf():
        inst = insts[node.id]
        cls = inst_to_class.get(inst, '?')
        print(f"{'  '*depth}└─ {inst:<14} [{cls:<18}]  {weight*100:6.3f}%")
        return [(inst, weight, cls)]
    # Internal node: find which instruments are in each sub-tree
    left_leaves = []
    right_leaves = []
    def collect(n, into):
        if n.is_leaf():
            into.append(insts[n.id])
        else:
            collect(n.left, into)
            collect(n.right, into)
    collect(node.left, left_leaves)
    collect(node.right, right_leaves)
    # Summary of each branch by asset class
    def cls_summary(lvs):
        d = {}
        for x in lvs:
            c = inst_to_class.get(x, '?')
            d[c] = d.get(c, 0) + 1
        return ', '.join(f"{v} {k}" for k,v in sorted(d.items(), key=lambda x:-x[1]))
    print(f"{'  '*depth}▶ split (n={len(left_leaves)+len(right_leaves)}, weight={weight*100:.2f}%):")
    print(f"{'  '*(depth+1)}L branch ({len(left_leaves)} inst, {weight/2*100:.2f}% → per-branch)")
    print(f"{'  '*(depth+1)}  {cls_summary(left_leaves)}")
    print(f"{'  '*(depth+1)}R branch ({len(right_leaves)} inst, {weight/2*100:.2f}% → per-branch)")
    print(f"{'  '*(depth+1)}  {cls_summary(right_leaves)}")
    results = walk(node.left, weight/2, depth+2)
    results += walk(node.right, weight/2, depth+2)
    return results

print("\n" + "="*100)
print("HANDCRAFT_SHRUNK BINARY TREE (50/50 at each split, 50% corr shrinkage)")
print("="*100)
leaves = walk(root, 1.0, 0)
print(f"\nTotal weight: {sum(w for _,w,_ in leaves)*100:.2f}%")
print(f"Max weight: {max(w for _,w,_ in leaves)*100:.2f}%")
print(f"Min weight: {min(w for _,w,_ in leaves)*100:.3f}%")

# Class-level summary
print("\n" + "="*60)
print("Cluster weight rollup (by our manual class labels)")
print("="*60)
cls_wts = {}
for inst, w, cls in leaves:
    cls_wts[cls] = cls_wts.get(cls, 0) + w
for cls, w in sorted(cls_wts.items(), key=lambda x:-x[1]):
    count = sum(1 for i, _, c in leaves if c == cls)
    print(f"  {cls:<22} {count:>2}inst  {w*100:>6.2f}%  avg/inst {w/count*100:.3f}%")

# Save dendrogram
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.cluster.hierarchy import dendrogram

fig, ax = plt.subplots(figsize=(20, 10))
CLASS_COLORS = {'Bonds':'#1f77b4','Grains':'#8c564b','Energy-Livestock':'#ff7f0e',
                'Equity-Risk':'#2ca02c','G10-FX':'#9467bd','EM-Metal-Crypto':'#e377c2'}
dendrogram(Z, labels=insts, leaf_rotation=90, leaf_font_size=9, ax=ax)
for lbl in ax.get_xticklabels():
    cls = inst_to_class.get(lbl.get_text(), '?')
    lbl.set_color(CLASS_COLORS.get(cls, 'black'))
import matplotlib.patches as mpatches
handles = [mpatches.Patch(color=c, label=k) for k,c in CLASS_COLORS.items()]
ax.legend(handles=handles, loc='upper right', fontsize=10)
ax.set_title("Handcraft_shrunk binary cluster tree (59 insts, Ward on shrunk corr distance)")
ax.set_ylabel(r"Distance √(0.5·(1−shrunk_corr))")
plt.tight_layout()
plt.savefig("/tmp/handcraft_tree_59.png", dpi=120)
print("\nDendrogram saved to /tmp/handcraft_tree_59.png")
