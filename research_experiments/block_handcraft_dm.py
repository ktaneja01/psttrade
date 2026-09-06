"""Carver handcrafting Step 4: DIVERSIFICATION MULTIPLIER on the block tree.

At each hierarchy node, instead of splitting risk equally (1/N) among children,
split PROPORTIONAL to each child's diversification multiplier (DM), so
well-diversified groups (uncorrelated members) claim more risk, redundant groups
(correlated members) claim less. DM computed on the 50%-shrunk correlation of the
node's children, capped at 2.5 (Carver). Recurse down; inverse-vol within leaf
blocks; 5% per-instrument cap.

Tree = explicit deep taxonomy (economic hierarchy), NOT the data linkage tree, so
DM is applied level-by-level exactly as Carver describes.
"""
import io, sys, warnings, numpy as np, pandas as pd; warnings.filterwarnings("ignore")

src = open("signals.py").read().split("# Build system with dynamic")[0]
ns = {}; o = sys.stdout; sys.stdout = io.StringIO(); exec(src, ns); sys.stdout = o
current = ns["FROZEN_HANDCRAFT_SHRUNK_WEIGHTS"]
# add newly-built STIR names to the universe (not yet in signals.py FROZEN dict)
universe = set(current.keys()) | {"EU-TECH","EU-HEALTH","EU-OIL","EU-AUTO"}

# explicit economic tree (nested); leaves = instrument lists
TREE = {
 "Equities": {
   "EM":          ["FTSECHINAA","MSCISING","HANG_mini"],
   "Dev-Country": ["SP500_micro","RUSSELL","NIKKEI","EUROSTX","FTSE100","SMI","TECDAX","AEX_mini"],
   "SmallCap":    ["EUROSTX-SMALL"],
   # Sector nested UNDER Equities (0.94 corr with country indices -> one equity bucket;
   # within-node DM correctly dilutes the correlated sectors).
   "Sector":      ["EU-BANKS","EU-BASIC","EU-INSURE","EU-TECH","EU-HEALTH","EU-OIL","EU-AUTO","US-REALESTATE"],
 },
 "Bonds": {
   "Govt":        ["US10","US30","BUND","GILT","BTP"],
   "IG-Credit":   ["IG"],   # separate: credit is a distinct factor (~0.36 corr to govt); 5% cap applies
 },
 "Commodities": {
   "Grains":      ["WHEAT","REDWHEAT","SOYBEAN","SOYMEAL","SOYOIL","CORN","RICE","CANOLA"],
   "Softs":       ["COFFEE","ROBUSTA","COCOA","OJ"],
   "Meats":       ["LIVECOW","FEEDCOW","LEANHOG"],
   "Precious":    ["GOLD_micro","SILVER-mini","PLAT","PALLAD"],
   "Base":        ["COPPER-micro","ALUMINIUM_LME","ZINC_LME","IRON"],
   "Energy": {   # nested: one Energy sub-unit (was 3 flat siblings -> gas/carbon over-weighted)
       "Oil":    ["CRUDE_W_micro","HEATOIL","GASOILINE","GASOIL"],
       "Gas":    ["GAS_US_mini"],
       "Carbon": ["EUA"],
   },
 },
 "FX": {
   "Dev":         ["EUR_micro","JPY","GBP_micro","AUD_micro","NZD","CHF","EURCAD"],
   "EM":          ["MXP","ZAR","BRE","PLN","NOK","SEK"],
 },
 "Volatility":    ["VIX"],
 "Crypto":        ["BITCOIN","ETHER-micro"],
}

def eret(code):
    adj=pd.to_numeric(pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").iloc[:,0],errors="coerce").dropna().resample("1B").last()
    carry=pd.to_numeric(pd.read_parquet(f"/usr/local/bc_data/futures_multiple_prices/{code}.parquet")["PRICE"],errors="coerce").resample("1B").last().reindex(adj.index).ffill()
    return (adj.diff()/carry.abs()).replace([np.inf,-np.inf],np.nan).rename(code)

# cache: vol-normalised WEEKLY return per instrument (for correlations) + ann vol
_norm={}; _vol={}
def load(code):
    if code in _norm: return
    r=eret(code); rw=r[r.index>="2016-01-01"].resample("W").sum()
    s=rw.std()
    _vol[code]=float(s*np.sqrt(52)) if s==s and s>1e-12 else np.nan
    _norm[code]=(rw/s) if s==s and s>1e-12 else None
for _,mem in [(b,m) for b,m in TREE.items()]:
    pass
def all_leaves(node):
    if isinstance(node,list):
        for i in node:
            if i in universe: yield i
    else:
        for v in node.values(): yield from all_leaves(v)
for i in all_leaves(TREE): load(i)

def prune(node):
    if isinstance(node,list):
        keep=[i for i in node if i in universe and _norm.get(i) is not None]
        return keep or None
    out={}
    for k,v in node.items():
        p=prune(v)
        if p: out[k]=p
    return out or None
T=prune(TREE)

# representative return series for a node = equal-weight of its leaves' normalised returns
def node_series(node):
    leaves=list(all_leaves(node)) if not isinstance(node,list) else [i for i in node if i in universe]
    cols=[_norm[i] for i in leaves if _norm.get(i) is not None]
    R=pd.concat(cols,axis=1)
    return R.mean(axis=1)

def shrunk_corr(series_list, shrink=0.5):
    M=pd.concat(series_list,axis=1).fillna(0)
    C=M.corr().values; n=C.shape[0]
    if n<2: return np.array([[1.0]])
    avg=C[~np.eye(n,dtype=bool)].mean()
    S=shrink*C+(1-shrink)*avg  # shrink=0.5 -> 50% toward avg
    np.fill_diagonal(S,1.0); return S

def div_mult(S, cap=2.5):
    n=S.shape[0]
    if n<2: return 1.0
    w=np.ones(n)/n
    port_var=float(w.dot(S).dot(w))
    if port_var<=0: return 1.0
    return min(1.0/np.sqrt(port_var), cap)

# recursive allocate with DM-proportional split
def allocate(node, risk):
    if isinstance(node, list):
        # leaf group: inverse-vol across instruments
        ivs=np.array([1.0/_vol[i] if _vol.get(i,np.nan)==_vol.get(i,np.nan) and _vol[i]>0 else 0 for i in node])
        if ivs.sum()<=0:
            return {i: risk/len(node) for i in node}
        ivs=ivs/ivs.sum()
        return {i: risk*wv for i,wv in zip(node,ivs)}
    kids=list(node.keys())
    child_dm={}
    for k in kids:
        sub=node[k]
        sl=[_norm[i] for i in sub if _norm.get(i) is not None] if isinstance(sub,list) \
           else [node_series(sub[g]) for g in sub]
        child_dm[k]=div_mult(shrunk_corr(sl)) if len(sl)>=2 else 1.0
    tot=sum(child_dm.values())
    out={}
    for k in kids:
        out.update(allocate(node[k], risk*(child_dm[k]/tot)))
    return out

w=allocate(T,1.0)

# Vol & Crypto branch caps at 5%; then 5% per-instrument cap
def leaves_of(name):
    return [i for i in all_leaves({name:T[name]})] if name in T else []
def cap_branch(w,mem,tot):
    cur=sum(w[i] for i in mem if i in w)
    if cur<=tot or cur<=0: return w
    exc=cur-tot
    for i in mem:
        if i in w: w[i]*=tot/cur
    oth=[k for k in w if k not in mem]; ot=sum(w[k] for k in oth)
    if ot>0:
        for k in oth: w[k]+=exc*(w[k]/ot)
    return w
w=cap_branch(w,leaves_of("Crypto"),0.05); w=cap_branch(w,leaves_of("Volatility"),0.05)
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

# ---- report: top-level + block totals vs current ----
def branch_tot(name,ws): return sum(ws[i] for i in all_leaves({name:T[name]}))
print("=== Carver Step-4 DIVERSIFICATION-MULTIPLIER allocation ===\n")
print(f"  {'top branch':14s}{'DM-alloc':>10s}{'current':>10s}")
for b in T:
    print(f"  {b:14s}{branch_tot(b,w)*100:>9.1f}%{sum(current.get(i,0) for i in all_leaves({b:T[b]}))*100:>9.1f}%")
print(f"  {'TOTAL':14s}{sum(w.values())*100:>9.1f}%")

# sub-block detail
print("\n=== sub-block DM-alloc vs current ===")
def subblocks(name):
    node=T[name]
    if isinstance(node,list): return [(name,node)]
    return [(f"{name}/{k}",all_leaves({k:node[k]}) if not isinstance(node[k],list) else node[k]) for k in node]
for b in T:
    for sbname,mem in subblocks(b):
        mem=list(mem)
        dt=sum(w.get(i,0) for i in mem)*100; cur=sum(current.get(i,0) for i in mem)*100
        print(f"  {sbname:22s}{dt:>7.1f}%{cur:>8.1f}%  ({dt-cur:+.1f})")

open("/tmp/dict_dm.txt","w").write(
  "FROZEN_HANDCRAFT_SHRUNK_WEIGHTS = {\n"+"".join(f'    "{k}": {v:.6f},\n' for k,v in sorted(w.items(),key=lambda x:-x[1]))+"}\n")
print("\nDM weights -> /tmp/dict_dm.txt")
