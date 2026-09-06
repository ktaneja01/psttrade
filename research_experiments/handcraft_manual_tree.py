"""Handcraft weights on an EXPLICIT hand-drawn hierarchy (not the auto-correlation
tree). Carver's manual handcraft: equal risk per branch, top-down, recursively;
inverse-vol within the final leaf group. Then vol-normalise to weights and 5% cap.

Tree (leaves = current 68-instrument universe mapped in):
Financial / Commodity at top, then the sub-branches the user specified.
"""
import io, sys, numpy as np, pandas as pd

src = open("signals.py").read().split("# Build system with dynamic")[0]
ns = {}; o = sys.stdout; sys.stdout = io.StringIO(); exec(src, ns); sys.stdout = o
universe = set(ns["FROZEN_HANDCRAFT_SHRUNK_WEIGHTS"].keys())

# ---- explicit tree (only instruments actually in the universe are kept) ----
TREE = {
 "Financial": {
   "Equities": {
     "Developed":  ["SP500_micro","RUSSELL","NIKKEI","EUROSTX","DAX","CAC","FTSE100","SMI","TECDAX","AEX_mini","SP400"],
     "Emerging":   ["FTSECHINAA","MSCISING","HANG_mini"],
     "Sectors":    ["EU-BANKS","EU-BASIC","EU-INSURE","EUROSTX-SMALL","US-REALESTATE"],
   },
   "Bonds": {
     "Long-end":   ["US10","US30","US20","US5","BUND","GILT","BTP","BOBL","SHATZ","OAT","BUXL","BONO","BTP3","CH10","CAD10","CAD5","CAD2","JGB","IG"],
     "Short-STIR": ["SOFR","FED","EURIBOR","SONIA3","BB3M","US2","US3"],
   },
   "FX": {
     "G10":        ["EUR_micro","JPY","GBP_micro","AUD_micro","NZD","CHF","EURCAD"],
     "EM":         ["MXP","ZAR","BRE","PLN","NOK","SEK"],
   },
   "Vol":          ["VIX"],
 },
 "Commodity": {
   "Ags": {
     "Grains":     ["CORN","WHEAT","REDWHEAT","SOYBEAN","SOYMEAL","SOYOIL","RICE","CANOLA"],
     "Softs":      ["COFFEE","ROBUSTA","COCOA","OJ"],
     "Livestock":  ["LIVECOW","FEEDCOW","LEANHOG"],
   },
   "Energy":       ["CRUDE_W_micro","BRENT_W","GAS_US","GAS_US_mini","HEATOIL","GASOILINE","GASOIL","EUA"],
   "Metals": {
     "Precious":   ["GOLD_micro","SILVER-mini","PLAT","PALLAD"],
     "Base":       ["COPPER-micro","ALUMINIUM_LME","ZINC_LME","IRON"],
   },
   "Crypto":       ["BITCOIN","ETHER-micro"],
 },
}

# ---- vols (annualised, engine-consistent recent) ----
def vol(code):
    try:
        adj = pd.to_numeric(pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").iloc[:,0], errors="coerce").dropna().resample("1B").last()
        carry = pd.to_numeric(pd.read_parquet(f"/usr/local/bc_data/futures_multiple_prices/{code}.parquet")["PRICE"], errors="coerce").resample("1B").last().reindex(adj.index).ffill()
        r = (adj.diff()/carry.abs()).replace([np.inf,-np.inf],np.nan).dropna().tail(1000)
        v = float(r.std()*np.sqrt(256))
        return v if v==v and v>1e-4 else None
    except Exception:
        return None

def prune(node):
    """keep only in-universe leaves; drop empty branches."""
    if isinstance(node, list):
        keep = [i for i in node if i in universe and vol(i) is not None]
        return keep or None
    out = {}
    for k, v in node.items():
        p = prune(v)
        if p: out[k] = p
    return out or None

def allocate(node, risk):
    """equal risk per branch top-down; inverse-vol at leaf list. returns {inst: risk_share}"""
    if isinstance(node, list):
        vs = np.array([vol(i) for i in node])
        iv = (1/vs); iv = iv/iv.sum()
        return {i: risk*w for i, w in zip(node, iv)}
    kids = list(node.keys()); each = risk/len(kids)
    out = {}
    for k in kids: out.update(allocate(node[k], each))
    return out

T = prune(TREE)
risk_alloc = allocate(T, 1.0)
w = risk_alloc

# ---- branch caps: Crypto <=5% total, Vol <=5% total (redistribute excess to
# other leaves proportionally) ----
def members_of(path_tuple):
    node = T
    for p in path_tuple:
        if p not in node: return []
        node = node[p]
    return [i for _, i in leaves({"x": node})] if not isinstance(node, list) else list(node)

def cap_branch(w, branch_members, cap_total):
    cur = sum(w[i] for i in branch_members if i in w)
    if cur <= cap_total or cur <= 0: return w
    scale = cap_total/cur
    excess = cur - cap_total
    for i in branch_members:
        if i in w: w[i] *= scale
    others = [k for k in w if k not in branch_members]
    ot = sum(w[k] for k in others)
    if ot > 0:
        for k in others: w[k] += excess*(w[k]/ot)
    return w

# need leaves() defined before use
def leaves(node, path=""):
    if isinstance(node, list):
        for i in node: yield path, i
    else:
        for k,v in node.items(): yield from leaves(v, f"{path}/{k}" if path else k)

crypto_members = [i for p,i in leaves(T) if p.endswith("Crypto")]
vol_members    = [i for p,i in leaves(T) if p.endswith("Vol")]
w = cap_branch(w, crypto_members, 0.05)
w = cap_branch(w, vol_members, 0.05)

# ---- 5% per-instrument cap with redistribution ----
def cap(w, cv=0.05):
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
w = cap(w)

# ---- print grouped by tree ----
def leaves(node, path=""):
    if isinstance(node, list):
        for i in node: yield path, i
    else:
        for k,v in node.items(): yield from leaves(v, f"{path}/{k}" if path else k)

from collections import defaultdict
branch_tot = defaultdict(float)
print(f"=== HANDCRAFT on MANUAL TREE ({len(w)} instruments) ===\n")
cur=None
for path, inst in leaves(T):
    top = path.split("/")[0]; sub = "/".join(path.split("/")[1:])
    branch_tot[path]+=w[inst]
    if path!=cur:
        print(f"\n{path}:"); cur=path
    print(f"    {inst:16s} {w[inst]*100:5.2f}%")

print("\n=== BRANCH TOTALS ===")
# roll up
def rollup(node, path=""):
    if isinstance(node, list):
        return sum(w[i] for i in node)
    tot=0
    for k,v in node.items():
        p=f"{path}/{k}" if path else k
        s=rollup(v,p); tot+=s
        print(f"  {p:32s} {s*100:5.1f}%")
    return tot
tot=rollup(T)
print(f"\n  {'TOTAL':32s} {tot*100:5.1f}%")

# top-level Financial vs Commodity
fin=rollup(T["Financial"]) if False else sum(w[i] for _,i in leaves({'x':T['Financial']}))
com=sum(w[i] for _,i in leaves({'x':T['Commodity']}))
print(f"\n  Financial {fin*100:.1f}%   |   Commodity {com*100:.1f}%")

# paste-ready dict
open("/tmp/dict_manual_tree.txt","w").write(
  "FROZEN_HANDCRAFT_SHRUNK_WEIGHTS = {\n"+"".join(f'    "{k}": {v:.6f},\n' for k,v in sorted(w.items(),key=lambda x:-x[1]))+"}\n")
print("\nPaste-ready dict -> /tmp/dict_manual_tree.txt")
