import os
"""Feed all 71 instruments into Carver's REAL handcraft_optimisation (automatic
binary-split correlation clustering), then roll the per-instrument weights up to
MY topology groups — to see what % allocation each of my economic buckets gets
under Carver's own clustering, vs my hand-drawn DM tree.
"""
import io, sys, warnings, numpy as np, pandas as pd; warnings.filterwarnings("ignore")
from sysquant.estimators.correlations import correlationEstimate
from sysquant.estimators.mean_estimator import meanEstimates
from sysquant.estimators.stdev_estimator import stdevEstimates
from sysquant.estimators.estimates import Estimates
from sysquant.optimisation.optimisers.handcraft import handcraft_optimisation

# universe = live signals.py (71 incl the 4 new sectors)
src = open(os.path.join(os.path.dirname(__file__),"..","signals.py")).read().split("# Build system with dynamic")[0]
ns = {}; o = sys.stdout; sys.stdout = io.StringIO(); exec(src, ns); sys.stdout = o
insts = list(dict.fromkeys(list(ns["FROZEN_HANDCRAFT_SHRUNK_WEIGHTS"].keys()) + ["EU-MEDIA","EU-DJ-TELECOM","EU-TRAVEL","US-ENERGY","US-FINANCE","US-HEALTH","US-TECH","US-INDUSTRY","US-MATERIAL","US-STAPLES"]))

# MY topology groups (same as the DM tree, flattened to top-level bucket per instrument)
TOPO = {
 "Equities": ["FTSECHINAA","MSCISING","HANG_mini","SP500_micro","RUSSELL","NIKKEI","EUROSTX","FTSE100","SMI","TECDAX","AEX_mini","EUROSTX-SMALL",
              "EU-BANKS","EU-BASIC","EU-INSURE","EU-TECH","EU-HEALTH","EU-OIL","EU-AUTO","EU-MEDIA","EU-DJ-TELECOM","EU-TRAVEL","US-REALESTATE",
              "US-ENERGY","US-FINANCE","US-HEALTH","US-TECH","US-INDUSTRY","US-MATERIAL","US-STAPLES"],
 "Bonds": ["US10","US30","BUND","GILT","BTP","IG"],
 "Commodities": ["WHEAT","REDWHEAT","SOYBEAN","SOYMEAL","SOYOIL","CORN","RICE","CANOLA","COFFEE","ROBUSTA","COCOA","OJ",
                 "LIVECOW","FEEDCOW","LEANHOG","GOLD_micro","SILVER-mini","PLAT","PALLAD","COPPER-micro","ALUMINIUM_LME","ZINC_LME","IRON",
                 "CRUDE_W_micro","HEATOIL","GASOILINE","GASOIL","GAS_US_mini","EUA"],
 "FX": ["EUR_micro","JPY","GBP_micro","AUD_micro","NZD","CHF","EURCAD","MXP","ZAR","BRE","PLN","NOK","SEK"],
 "Volatility": ["VIX"],
 "Crypto": ["BITCOIN","ETHER-micro"],
}
i2g = {i:g for g,v in TOPO.items() for i in v}

# engine-consistent weekly returns (diff/carry), 2016+, exactly like freeze script
def wret(code):
    adj=pd.to_numeric(pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").iloc[:,0],errors="coerce").dropna().resample("1B").last().ffill()
    carry=pd.to_numeric(pd.read_parquet(f"/usr/local/bc_data/futures_multiple_prices/{code}.parquet")["PRICE"],errors="coerce").resample("1B").last().reindex(adj.index).ffill()
    r=(adj.diff()/carry).replace([np.inf,-np.inf],np.nan).dropna()
    return r.resample("W").sum().rename(code)

rets=pd.concat([wret(i) for i in insts],axis=1)
rets=rets[rets.index>="2016-01-01"].dropna(thresh=int(len(insts)*0.5)).fillna(0)
insts=[i for i in insts if i in rets.columns]

corr_df=rets.corr(); vol=rets.std()*np.sqrt(52); mean=rets.mean()*52
est=Estimates(
    correlation=correlationEstimate(values=corr_df.values, columns=list(corr_df.columns)),
    mean=meanEstimates({i:float(mean[i]) for i in insts}),
    stdev=stdevEstimates({i:float(vol[i]) for i in insts}),
    data_length=len(rets), frequency="W")
est=est.shrink_correlation_to_average(0.5)
out=handcraft_optimisation(est, equalise_SR=True, equalise_vols=True)
w=dict(out.weights)

# 5% cap (same as production)
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
wc=cap(w)

# roll up to my topology
from collections import defaultdict
grp=defaultdict(float); cnt=defaultdict(int)
for i,wt in wc.items():
    g=i2g.get(i,"?"); grp[g]+=wt; cnt[g]+=1
print("=== CARVER auto-handcraft (binary-split clustering) rolled to MY topology ===\n")
print(f"  {'group':14s}{'handcraft':>11s}{'  (my DM-tree)'}")
dmtree={"Equities":21.0,"Bonds":16.1,"Commodities":32.6,"FX":19.4,"Volatility":5.0,"Crypto":5.9}
for g in ["Equities","Bonds","Commodities","FX","Volatility","Crypto"]:
    print(f"  {g:14s}{grp[g]*100:>10.1f}%   {dmtree.get(g,0):>5.1f}%   ({cnt[g]} inst)")
print(f"  {'TOTAL':14s}{sum(grp.values())*100:>10.1f}%")
# also dump the handcraft's own top clusters for insight
print(f"\n  (handcraft max weight {max(wc.values())*100:.2f}%, min {min(wc.values())*100:.2f}%)")

# paste-ready dict for backtest
open("/tmp/dict_handcraft.txt","w").write(
  "FROZEN_HANDCRAFT_SHRUNK_WEIGHTS = {\n"+"".join(f'    "{k}": {v:.6f},\n' for k,v in sorted(wc.items(),key=lambda x:-x[1]))+"}\n")
print("handcraft dict ->", len(wc), "inst -> /tmp/dict_handcraft.txt")
