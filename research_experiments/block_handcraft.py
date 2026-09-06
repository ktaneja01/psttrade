"""Run handcraft (equal-risk-per-branch, top-down) on the 17 sub-asset BLOCKS using
the 50%-shrunk block correlation tree, then distribute each block's risk to its
instruments by inverse-vol. Compare the resulting instrument weights + block totals
to the current option-c FROZEN weights.

This is 'is my allocation right?' answered by data-driven block clustering rather
than the hand-drawn taxonomy weights.
"""
import io, sys, warnings, numpy as np, pandas as pd; warnings.filterwarnings("ignore")
from scipy.cluster import hierarchy as sch

src = open("signals.py").read().split("# Build system with dynamic")[0]
ns = {}; o = sys.stdout; sys.stdout = io.StringIO(); exec(src, ns); sys.stdout = o
current = ns["FROZEN_HANDCRAFT_SHRUNK_WEIGHTS"]
universe = set(current.keys())

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
BLOCKS = {b:[m for m in mem if m in universe] for b,mem in BLOCKS.items()}
BLOCKS = {b:mem for b,mem in BLOCKS.items() if mem}

def eret(code):
    adj=pd.to_numeric(pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").iloc[:,0],errors="coerce").dropna().resample("1B").last()
    carry=pd.to_numeric(pd.read_parquet(f"/usr/local/bc_data/futures_multiple_prices/{code}.parquet")["PRICE"],errors="coerce").resample("1B").last().reindex(adj.index).ffill()
    return (adj.diff()/carry.abs()).replace([np.inf,-np.inf],np.nan).rename(code)

# instrument vols (annualised) + block return series (vol-normalised equal-weight)
inst_vol={}; block_ret={}
for b,mem in BLOCKS.items():
    cols=[]
    for m in mem:
        r=eret(m); s=r.std()
        if s and s==s and s>1e-12:
            inst_vol[m]=float(s*np.sqrt(52))  # weekly->annual later; keep consistent below
            cols.append(r/s)
    R=pd.concat(cols,axis=1); block_ret[b]=R.mean(axis=1)
B=pd.concat(block_ret,axis=1); B=B[B.index>="2016-01-01"].resample("W").sum().fillna(0)
blocks=list(B.columns); n=len(blocks)
# recompute annualised inst vol on weekly
for b,mem in BLOCKS.items():
    for m in mem:
        r=eret(m).reindex(B.index if False else eret(m).index)
for m in list(inst_vol):
    r=eret(m); rw=r[r.index>="2016-01-01"].resample("W").sum()
    v=float(rw.std()*np.sqrt(52)); inst_vol[m]=v if v==v and v>1e-9 else np.nan

# shrunk block corr + complete-linkage tree
C=B.corr().values; avg=C[~np.eye(n,dtype=bool)].mean()
S=0.5*C+0.5*avg; np.fill_diagonal(S,1.0)
d=sch.distance.pdist(S); L=sch.linkage(d,method="complete")

# ---- equal-risk-per-branch top-down over the linkage tree ----
# Build the tree, recursively split risk 50/50 at each internal node down to leaves.
from scipy.cluster.hierarchy import to_tree
root=to_tree(L)
block_risk={}
def descend(node,risk):
    if node.is_leaf():
        block_risk[blocks[node.id]]=risk; return
    # equal risk to each child branch (Carver handcraft)
    descend(node.left,risk/2.0); descend(node.right,risk/2.0)
descend(root,1.0)

# ---- within each block: inverse-vol across its instruments ----
w={}
for b,mem in BLOCKS.items():
    br=block_risk[b]
    ivs=np.array([1.0/inst_vol[m] if inst_vol.get(m,np.nan)==inst_vol.get(m,np.nan) and inst_vol[m]>0 else 0 for m in mem])
    if ivs.sum()<=0:
        for m in mem: w[m]=br/len(mem)
        continue
    ivs=ivs/ivs.sum()
    for m,iv in zip(mem,ivs): w[m]=br*iv
# 5% per-instrument cap
def cap(w,cv=0.05):
    w=dict(w); capped=set()
    while True:
        over={k:v for k,v in w.items() if v>cv and k not in capped}
        if not over: break
        exc=sum(v-cv for v in over.values())
        for k in over: w[k]=cv; capped.add(k)
        u={k:v for k,v in w.items() if k not in capped}; ut=sum(u.values())
        if ut<=0: break
        for k in u: w[k]+=exc*(u[k]/ut)
    t=sum(w.values()); return {k:v/t for k,v in w.items()}
w=cap(w)

# ---- compare block totals: data-driven vs current ----
print("=== BLOCK RISK: data-driven equal-risk-per-branch  vs  current option-c ===\n")
print(f"  {'block':16s}{'DATA-TREE':>11s}{'CURRENT':>10s}{'  diff':>8s}")
for b,mem in sorted(BLOCKS.items(),key=lambda x:-sum(w[m] for m in x[1])):
    dt=sum(w[m] for m in mem)*100
    cur=sum(current.get(m,0) for m in mem)*100
    print(f"  {b:16s}{dt:>10.1f}%{cur:>9.1f}%{dt-cur:>+8.1f}")
# top-level super-clusters (K=4)
print("\n=== top-level (K=4 clusters) ===")
ind=sch.fcluster(L,4,criterion="maxclust")
cl={}
for b,g in zip(blocks,ind): cl.setdefault(g,[]).append(b)
for g,bs in cl.items():
    dt=sum(w[m] for b in bs for m in BLOCKS[b])*100
    cur=sum(current.get(m,0) for b in bs for m in BLOCKS[b])*100
    print(f"  DATA {dt:5.1f}% | CUR {cur:5.1f}%  :: {', '.join(bs)}")

open("/tmp/dict_blocktree.txt","w").write(
  "FROZEN_HANDCRAFT_SHRUNK_WEIGHTS = {\n"+"".join(f'    "{k}": {v:.6f},\n' for k,v in sorted(w.items(),key=lambda x:-x[1]))+"}\n")
print("\nData-tree weights -> /tmp/dict_blocktree.txt")
