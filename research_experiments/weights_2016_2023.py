"""Compute handcraft_shrunk weights using ONLY returns up to 2023-12-31."""
import sys
import numpy as np
import pandas as pd

from sysquant.estimators.correlations import correlationEstimate
from sysquant.estimators.mean_estimator import meanEstimates
from sysquant.estimators.stdev_estimator import stdevEstimates
from sysquant.estimators.estimates import Estimates
from sysquant.optimisation.optimisers.handcraft import handcraft_optimisation

CUTOFF = "2023-12-31"

bad = {"US2","US3","US5","EURCHF","GBPEUR","CAD","SOFR1","LUMBER-new","OATIES",
       "STEEL","BRENT_W","SHATZ","BOBL","COTTON2","SUGAR11","SP500","GOLD"}
raw = {
    "Bonds": ["US2","US3","US5","US10","US10U","US20","US30","SOFR1","BOBL","BUND","SHATZ","GILT"],
    "Grains": ["REDWHEAT","SOYMEAL","SOYOIL","WHEAT","CORN","SOYBEAN","OATIES"],
    "Energy-Livestock": ["CRUDE_W","BRENT_W","GAS_US","GASOILINE","HEATOIL","GAS-LAST",
                         "LIVECOW","FEEDCOW","LEANHOG","RICE","LUMBER-new","GBPJPY",
                         "COFFEE","OJ","GASOIL","COCOA"],
    "Equity-Risk": ["SP500","NASDAQ","RUSSELL","DOW","NIKKEI","SP400",
                    "CAC","DAX","EUROSTX","FTSE100","VIX","V2X"],
    "G10-FX": ["EUR","JPY","GBP","AUD","NZD","CHF","CAD","EURCHF","GBPEUR","PLN","EURCAD","DX"],
    "EM-Metal-Crypto": ["MXP","ZAR","BRE","GOLD","SILVER","COPPER","PLAT","PALLAD","STEEL","BITCOIN","ETHEREUM"],
}
insts = [i for vs in raw.values() for i in vs if i not in bad]

def r(c):
    s = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{c}.parquet").squeeze()
    s = s.dropna().resample("1B").last().ffill(); s = s[s>0]
    return s.pct_change().dropna().resample("W").sum().rename(c)

rets = pd.concat([r(i) for i in insts], axis=1)
rets = rets[(rets.index>="2016-01-01") & (rets.index<=CUTOFF)].dropna(thresh=int(len(insts)*0.5)).fillna(0)
print(f"Training window: {rets.index.min().date()} → {rets.index.max().date()} ({len(rets)} weeks)", flush=True)

corr = rets.corr(); vols = rets.std()*np.sqrt(52); means = rets.mean()*52
est = Estimates(
    correlation=correlationEstimate(values=corr.values, columns=list(corr.columns)),
    mean=meanEstimates({i: float(means[i]) for i in insts}),
    stdev=stdevEstimates({i: float(vols[i]) for i in insts}),
    data_length=len(rets), frequency="W",
).shrink_correlation_to_average(0.5)

out = handcraft_optimisation(est, equalise_SR=True, equalise_vols=True)
raw_w = dict(out.weights)

def cap(w, c=0.05):
    w = dict(w)
    while True:
        over = {k:v for k,v in w.items() if v>c}
        if not over: break
        exc = sum(v-c for v in over.values())
        und = {k:v for k,v in w.items() if v<=c}
        if not und: break
        ut = sum(und.values())
        for k in over: w[k]=c
        for k in und: w[k] += exc*(und[k]/ut)
    t = sum(w.values())
    return {k:v/t for k,v in w.items()}

final = cap(raw_w, 0.05)
print(f"\nFROZEN_HANDCRAFT_SHRUNK_WEIGHTS_2023 = {{")
for k in sorted(final, key=lambda x: -final[x]):
    print(f'    "{k}": {final[k]:.6f},')
print("}")
print(f"\nN={len(final)}, sum={sum(final.values()):.4f}, max={max(final.values())*100:.2f}%, min={min(final.values())*100:.3f}%",flush=True)
