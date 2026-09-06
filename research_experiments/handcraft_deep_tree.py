"""Handcraft on Carver's DEEP taxonomy (user-specified). Equal risk per branch,
top-down recursively; inverse-vol at the leaf list. Caps: Crypto<=5%, Vol<=5%,
5% per-instrument. Interest-rates (STIR) is a SEPARATE top-level branch from Bonds
(currently empty -> pruned; ready for SOFR/FED/EURIBOR when they download).

Top level branches get equal risk. Empty branches are pruned before splitting so
they don't steal risk.
"""
import io, sys, numpy as np, pandas as pd

src = open("signals.py").read().split("# Build system with dynamic")[0]
ns = {}; o = sys.stdout; sys.stdout = io.StringIO(); exec(src, ns); sys.stdout = o
universe = set(ns["FROZEN_HANDCRAFT_SHRUNK_WEIGHTS"].keys())

# ---- Carver deep taxonomy mapped to the 67-instrument universe ----
TREE = {
 "Equities": {
   "Emerging": {
     "Countries": ["FTSECHINAA","MSCISING","HANG_mini"],
   },
   "Developed": {
     "Countries": ["SP500_micro","RUSSELL","NIKKEI","EUROSTX","FTSE100","SMI","TECDAX","AEX_mini"],
     "Sectors":   ["EU-BANKS","EU-BASIC","EU-INSURE","EUROSTX-SMALL","US-REALESTATE"],
   },
 },
 "Bonds": {
   "Developed": {
     "Corporate": {
       "InvestmentGrade": ["IG"],       # iBoxx $ IG credit
     },
     "Government": ["US10","US30","BUND","GILT","BTP"],   # long-end govvies
   },
 },
 "InterestRates": {   # STIR — separate top-level branch (Carver taxonomy)
   # SOFR/FED/EURIBOR/SONIA go here when downloaded; empty now -> pruned
   "Country": [],
 },
 "Commodities": {
   "Ags": {
     "Grains": {
       "Wheat": ["WHEAT","REDWHEAT"],
       "Soy":   ["SOYBEAN","SOYMEAL","SOYOIL"],
       "Other": ["CORN","RICE","CANOLA"],
     },
     "Softs":     ["COFFEE","ROBUSTA","COCOA","OJ"],
     "Meats":     ["LIVECOW","FEEDCOW","LEANHOG"],
   },
   "Metals": {
     "Precious":  ["GOLD_micro","SILVER-mini","PLAT","PALLAD"],
     "Base":      ["COPPER-micro","ALUMINIUM_LME","ZINC_LME","IRON"],
   },
   "Energies": {
     "OilAndProducts": ["CRUDE_W_micro","HEATOIL","GASOILINE","GASOIL"],
     "Gas":            ["GAS_US_mini"],
     "Carbon":         ["EUA"],
   },
 },
 "FX": {
   "Developed": ["EUR_micro","JPY","GBP_micro","AUD_micro","NZD","CHF","EURCAD"],
   "Emerging":  ["MXP","ZAR","BRE","PLN","NOK","SEK"],
 },
 "Volatility": ["VIX"],
 "Crypto":     ["BITCOIN","ETHER-micro"],
}

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
    if isinstance(node, list):
        keep=[i for i in node if i in universe and vol(i) is not None]
        return keep or None
    out={}
    for k,v in node.items():
        p=prune(v)
        if p: out[k]=p
    return out or None

def allocate(node, risk):
    if isinstance(node, list):
        vs=np.array([vol(i) for i in node]); iv=1/vs; iv=iv/iv.sum()
        return {i: risk*w for i,w in zip(node,iv)}
    kids=list(node.keys()); each=risk/len(kids); out={}
    for k in kids: out.update(allocate(node[k], each))
    return out

def leaves(node, path=""):
    if isinstance(node, list):
        for i in node: yield path, i
    else:
        for k,v in node.items(): yield from leaves(v, f"{path}/{k}" if path else k)

T = prune(TREE)

# ---- FIXED top-level target weights (do NOT let empty/capped branches inflate
# the survivors "equally"). Empty branches (InterestRates, Alts) + any capped
# excess are redistributed ONLY to the growth branches: Equities/Bonds/Commodities.
# FX pinned at 12.5% (Developed 6.25 / Emerging 6.25); Vol 5%; Crypto 5%.
TOP_TARGET = {
    "Equities":    0.20,
    "Bonds":       0.20,
    "Commodities": 0.20,
    "InterestRates": 0.125,   # empty now -> its share flows to the 3 growth branches
    "FX":          0.125,     # PINNED
    "Volatility":  0.05,
    "Crypto":      0.05,
    # "Alts":      0.0        # none
}
# Option (c): empty-branch target (InterestRates 12.5%) is redistributed
# PROPORTIONALLY across ALL populated branches (incl FX, Vol, Crypto), i.e. every
# present branch simply scales up by the same factor. FX is NOT pinned here.
present = set(T.keys())
target = {b: t for b, t in TOP_TARGET.items() if b in present}
s = sum(target.values()); target = {k: v/s for k, v in target.items()}   # scale all up evenly

# allocate each top branch its fixed target, recurse inside
w = {}
for b, t in target.items():
    w.update(allocate(T[b], t))

# branch caps (Vol/Crypto already targeted at 5%, but enforce + per-instrument)
crypto_m=[i for p,i in leaves(T) if p.split("/")[0]=="Crypto"]
vol_m   =[i for p,i in leaves(T) if p.split("/")[0]=="Volatility"]
def cap_branch(w, mem, tot, protect):
    """cap a branch to `tot`, redistribute excess ONLY to `protect` branches' members."""
    cur=sum(w[i] for i in mem if i in w)
    if cur<=tot or cur<=0: return w
    exc=cur-tot
    for i in mem:
        if i in w: w[i]*=tot/cur
    pm=[i for i in protect if i in w]; pt=sum(w[i] for i in pm)
    if pt>0:
        for i in pm: w[i]+=exc*(w[i]/pt)
    return w
# option (c): Vol/Crypto excess redistributes proportionally across ALL other members
non_volcrypto=[i for p,i in leaves(T) if p.split("/")[0] not in ("Crypto","Volatility")]
w=cap_branch(w,crypto_m,0.05,non_volcrypto); w=cap_branch(w,vol_m,0.05,non_volcrypto)
fx_members=set(i for p,i in leaves(T) if p.split("/")[0]=="FX")
def cap(w,cv=0.05,pin=frozenset()):
    """per-instrument cap; `pin` members never RECEIVE redistribution (weights held)."""
    w=dict(w); capped=set()
    while True:
        over={k:v for k,v in w.items() if v>cv and k not in capped}
        if not over: break
        exc=sum(v-cv for v in over.values())
        for k in over: w[k]=cv; capped.add(k)
        u={k:v for k,v in w.items() if k not in capped and k not in pin}; ut=sum(u.values())
        if ut<=0: break
        for k in u: w[k]+=exc*(u[k]/ut)
    t=sum(w.values()); return {k:v/t for k,v in w.items()}
w=cap(w)   # option (c): no FX pin — all populated branches scaled evenly

# ---- print tree with per-leaf weights + rolled-up branch totals ----
print(f"=== HANDCRAFT on CARVER DEEP TAXONOMY ({len(w)} instruments) ===\n")
def show(node, path="", depth=0):
    ind="  "*depth
    if isinstance(node, list):
        for i in node:
            print(f"{ind}{i:18s} {w[i]*100:5.2f}%")
        return sum(w[i] for i in node)
    tot=0
    for k,v in node.items():
        s= show(v, f"{path}/{k}", depth+1) if False else None
        # compute subtotal first
        sub=sum(w[i] for _,i in leaves(v))
        print(f"{ind}{k:22s} [{sub*100:4.1f}%]")
        show(v, f"{path}/{k}", depth+1)
        tot+=sub
    return tot
show(T)
# top-level split
print("\n=== TOP-LEVEL BRANCH RISK ===")
for k in T:
    s=sum(w[i] for _,i in leaves({k:T[k]}))
    print(f"  {k:16s} {s*100:5.1f}%")
print(f"  {'TOTAL':16s} {sum(w.values())*100:5.1f}%")
open("/tmp/dict_deep_tree.txt","w").write(
  "FROZEN_HANDCRAFT_SHRUNK_WEIGHTS = {\n"+"".join(f'    "{k}": {v:.6f},\n' for k,v in sorted(w.items(),key=lambda x:-x[1]))+"}\n")
print("\nPaste-ready dict -> /tmp/dict_deep_tree.txt")
