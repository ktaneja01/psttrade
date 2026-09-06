"""Block-level (asset/sub-asset) clustering dendrogram.
Instead of clustering 67 instruments, aggregate them into sub-asset BLOCKS
(from the deep taxonomy), build an equal-weighted engine-consistent return series
per block, compute the block correlation matrix, shrink 50% toward the average
off-diagonal correlation (handcraft), and cluster (complete linkage on corr, the
method handcraft uses internally). Renders the block dendrogram + prints the
shrunk block correlation matrix.
"""
import io, sys, warnings, numpy as np, pandas as pd; warnings.filterwarnings("ignore")
from scipy.cluster import hierarchy as sch
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

src = open("signals.py").read().split("# Build system with dynamic")[0]
ns = {}; o = sys.stdout; sys.stdout = io.StringIO(); exec(src, ns); sys.stdout = o
universe = set(ns["FROZEN_HANDCRAFT_SHRUNK_WEIGHTS"].keys())

# ---- sub-asset BLOCKS (leaf groups of the deep taxonomy) ----
BLOCKS = {
 "Eq/EM":         ["FTSECHINAA","MSCISING","HANG_mini"],
 "Eq/Dev-Country":["SP500_micro","RUSSELL","NIKKEI","EUROSTX","FTSE100","SMI","TECDAX","AEX_mini"],
 "Eq/Dev-Sector": ["EU-BANKS","EU-BASIC","EU-INSURE","EUROSTX-SMALL","US-REALESTATE"],
 "Bond/Govt":     ["US10","US30","BUND","GILT","BTP"],
 "Bond/IG-Credit":["IG"],
 "Ags/Grains":    ["WHEAT","REDWHEAT","SOYBEAN","SOYMEAL","SOYOIL","CORN","RICE","CANOLA"],
 "Ags/Softs":     ["COFFEE","ROBUSTA","COCOA","OJ"],
 "Ags/Meats":     ["LIVECOW","FEEDCOW","LEANHOG"],
 "Metal/Precious":["GOLD_micro","SILVER-mini","PLAT","PALLAD"],
 "Metal/Base":    ["COPPER-micro","ALUMINIUM_LME","ZINC_LME","IRON"],
 "Energy/Oil":    ["CRUDE_W_micro","HEATOIL","GASOILINE","GASOIL"],
 "Energy/Gas":    ["GAS_US_mini"],
 "Energy/Carbon": ["EUA"],
 "FX/Dev":        ["EUR_micro","JPY","GBP_micro","AUD_micro","NZD","CHF","EURCAD"],
 "FX/EM":         ["MXP","ZAR","BRE","PLN","NOK","SEK"],
 "Vol":           ["VIX"],
 "Crypto":        ["BITCOIN","ETHER-micro"],
}

def eret(code):
    adj=pd.to_numeric(pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").iloc[:,0],errors="coerce").dropna().resample("1B").last()
    carry=pd.to_numeric(pd.read_parquet(f"/usr/local/bc_data/futures_multiple_prices/{code}.parquet")["PRICE"],errors="coerce").resample("1B").last().reindex(adj.index).ffill()
    return (adj.diff()/carry.abs()).replace([np.inf,-np.inf],np.nan).rename(code)

# block return = equal-weight avg of vol-normalised instrument returns (so no single
# high-vol name dominates the block series)
block_ret={}
for b,members in BLOCKS.items():
    members=[m for m in members if m in universe]
    if not members: continue
    cols=[]
    for m in members:
        r=eret(m)
        s=r.std()
        if s and s==s and s>1e-12: cols.append((r/s))   # vol-normalise each
    if not cols: continue
    R=pd.concat(cols,axis=1)
    block_ret[b]=R.mean(axis=1)   # equal-weight the normalised members
B=pd.concat(block_ret,axis=1)
B=B[B.index>="2016-01-01"].resample("W").sum().fillna(0)
blocks=list(B.columns); n=len(blocks)

# ---- correlation + 50% shrink toward average off-diagonal (handcraft) ----
C=B.corr().values
avg=C[~np.eye(n,dtype=bool)].mean()
S=0.5*C+0.5*avg; np.fill_diagonal(S,1.0)
print(f"{n} blocks | avg off-diag corr {avg:.3f} (shrunk 50% toward it)\n")

# ---- cluster: complete linkage on the (shrunk) correlation rows (handcraft method) ----
d=sch.distance.pdist(S); L=sch.linkage(d,method="complete")

fig,ax=plt.subplots(figsize=(12,8))
dn=sch.dendrogram(L,labels=blocks,orientation="left",ax=ax,
                  color_threshold=0.7*max(L[:,2]),leaf_font_size=10)
ax.set_title("Block (asset/sub-asset) dendrogram — complete linkage on 50%-shrunk correlation\n"
             "(handcraft clustering at the block level, not instrument level)",fontsize=11)
ax.set_xlabel("cluster distance")
plt.tight_layout(); plt.savefig("/tmp/block_dendro.png",dpi=120)
print("Dendrogram -> /tmp/block_dendro.png\n")

# ---- print shrunk block correlation matrix (rounded) ----
Sdf=pd.DataFrame(S,index=blocks,columns=blocks)
print("=== shrunk block correlation matrix ===")
print(Sdf.round(2).to_string())

# ---- show cluster groupings at a few cut levels ----
print("\n=== block clusters at K cut levels ===")
for K in [4,6,8]:
    ind=sch.fcluster(L,K,criterion="maxclust")
    groups={}
    for b,g in zip(blocks,ind): groups.setdefault(g,[]).append(b)
    print(f"  K={K}: "+" | ".join("{"+", ".join(v)+"}" for v in groups.values()))
