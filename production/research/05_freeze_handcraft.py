"""Stage 5 — freeze instrument weights via Carver handcraft_optimisation on the
CURATED store. Deterministic: same curated data -> same weights.

Method (matches the production allocation): engine-consistent weekly returns
(diff(adjusted)/carry_price) from 2016+, correlation shrunk 50% toward the average,
handcraft_optimisation(equalise_SR=True, equalise_vols=True), then a 5% per-instrument
cap with redistribution. Emits artifacts/handcraft_weights.txt (paste-ready dict).

Run:  pst-env/bin/python3 production/research/05_freeze_handcraft.py
"""
import os, io, sys, json, warnings, numpy as np, pandas as pd
warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
os.chdir(ROOT)
CFG = json.load(open(os.path.join(HERE, "config.json")))
CUR = os.path.join(HERE, "data", "curated_rolladjusted")
ADJ = os.path.join(CUR, "futures_adjusted_prices")
MULT = os.path.join(CUR, "futures_multiple_prices")

from sysquant.estimators.correlations import correlationEstimate
from sysquant.estimators.mean_estimator import meanEstimates
from sysquant.estimators.stdev_estimator import stdevEstimates
from sysquant.estimators.estimates import Estimates
from sysquant.optimisation.optimisers.handcraft import handcraft_optimisation

insts = list(CFG["universe"])

def wret(code):
    adj = pd.to_numeric(pd.read_parquet(f"{ADJ}/{code}.parquet").iloc[:, 0], errors="coerce") \
            .dropna().resample("1B").last().ffill()
    carry = pd.to_numeric(pd.read_parquet(f"{MULT}/{code}.parquet")["PRICE"], errors="coerce") \
              .resample("1B").last().reindex(adj.index).ffill()
    return (adj.diff() / carry).replace([np.inf, -np.inf], np.nan).dropna().resample("W").sum().rename(code)

rets = pd.concat([wret(i) for i in insts], axis=1)
rets = rets[rets.index >= "2016-01-01"].dropna(thresh=int(len(insts) * 0.5)).fillna(0)
insts = [i for i in insts if i in rets.columns]
corr = rets.corr(); vol = rets.std() * np.sqrt(52); mean = rets.mean() * 52
est = Estimates(
    correlation=correlationEstimate(values=corr.values, columns=list(corr.columns)),
    mean=meanEstimates({i: float(mean[i]) for i in insts}),
    stdev=stdevEstimates({i: float(vol[i]) for i in insts}),
    data_length=len(rets), frequency="W").shrink_correlation_to_average(0.5)
w = dict(handcraft_optimisation(est, equalise_SR=True, equalise_vols=True).weights)

def cap(w, cv=0.05):
    w = dict(w); capped = set()
    while True:
        over = {k: v for k, v in w.items() if v > cv and k not in capped}
        if not over:
            break
        exc = sum(v - cv for v in over.values())
        for k in over:
            w[k] = cv; capped.add(k)
        u = {k: v for k, v in w.items() if k not in capped}; ut = sum(u.values())
        if ut <= 0:
            break
        for k in u:
            w[k] += exc * (u[k] / ut)
    t = sum(w.values()); return {k: v / t for k, v in w.items()}

wc = cap(w)
out = "FROZEN_HANDCRAFT_SHRUNK_WEIGHTS = {\n" + \
      "".join(f'    "{k}": {v:.6f},\n' for k, v in sorted(wc.items(), key=lambda x: -x[1])) + "}\n"
open(os.path.join(HERE, "artifacts", "handcraft_weights.txt"), "w").write(out)
print(f"handcraft: {len(wc)} instruments, sum={sum(wc.values()):.4f}, max={max(wc.values())*100:.2f}%")
print("-> artifacts/handcraft_weights.txt")
