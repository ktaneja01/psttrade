"""Show the empirical correlation clustering on CLEAN data (post data-repair).
Uses engine-consistent returns (diff/carry_price). Prints K clusters grouped by
AssetClass, with intra-cluster correlation. Default 6yr window, K=8.

  python cluster_report.py [years] [K]
"""
import sys, re, io
import numpy as np, pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform
from collections import Counter

YEARS = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
K = int(sys.argv[2]) if len(sys.argv) > 2 else 8
END = pd.Timestamp("2026-04-19")
START = END - pd.Timedelta(days=int(365 * YEARS))

sig = open("signals.py").read()
b = sig.split("FROZEN_HANDCRAFT_SHRUNK_WEIGHTS = {")[1].split("}")[0]
instruments = [m.group(1) for m in re.finditer(r'"([^"]+)":', b)]
_o = sys.stdout; sys.stdout = io.StringIO()
ns = {}; exec(sig.split("# Build system with dynamic optimisation")[0], ns)
sys.stdout = _o
i2c = {i: c for c, insts in ns["asset_classes"].items() for i in insts}


def eret(code):
    adj = pd.to_numeric(pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").iloc[:, 0], errors="coerce").dropna().resample("1B").last()
    carry = pd.to_numeric(pd.read_parquet(f"/usr/local/bc_data/futures_multiple_prices/{code}.parquet")["PRICE"], errors="coerce").resample("1B").last().reindex(adj.index).ffill()
    return (adj.diff() / carry.abs()).replace([np.inf, -np.inf], np.nan).rename(code)


rets = pd.concat([eret(i) for i in instruments], axis=1)
win = rets[(rets.index >= START) & (rets.index <= END)]
win = win.loc[:, win.std() > 1e-12]
insts = list(win.columns)
C = win.corr(min_periods=104).values
ca = np.nanmean(np.where(np.eye(len(insts), dtype=bool), np.nan, C), axis=0)
for a, bb in zip(*np.where(np.isnan(C))):
    C[a, bb] = ca[bb] if not np.isnan(ca[bb]) else 0.0
np.fill_diagonal(C, 1.0)
n = len(insts)
avg = C[~np.eye(n, dtype=bool)].mean()
S = 0.5 * C + 0.5 * avg; np.fill_diagonal(S, 1.0)
D = np.sqrt(np.clip(0.5 * (1 - S), 0, None)); np.fill_diagonal(D, 0)
Z = linkage(squareform(D, checks=False), method="complete")
labels = fcluster(Z, t=K, criterion="maxclust")
clusters = {cid: [insts[i] for i in range(n) if labels[i] == cid] for cid in sorted(set(labels))}


def intra(mem):
    idx = [insts.index(m) for m in mem]; sub = C[np.ix_(idx, idx)]
    off = sub[~np.eye(len(mem), dtype=bool)]
    return off.mean() if len(off) else float("nan")


print(f"CLEAN-DATA clustering: {YEARS:.0f}yr {START.date()}..{END.date()}, {n} instruments, K={K}\n")
for k, cid in enumerate(sorted(clusters, key=lambda c: -len(clusters[c])), 1):
    mem = clusters[cid]; cc = Counter(i2c.get(m, "?") for m in mem)
    print(f"CLUSTER {k}  (n={len(mem)}, intra {intra(mem):+.2f})  [{', '.join(f'{v} {kk}' for kk, v in cc.most_common())}]")
    byc = {}
    for m in mem: byc.setdefault(i2c.get(m, "?"), []).append(m)
    for cls, ms in sorted(byc.items(), key=lambda x: -len(x[1])):
        print(f"     {cls:18s} {', '.join(sorted(ms))}")
    print()
# spot-check: which cluster is SILVER + GOLD in?
for cid, mem in clusters.items():
    if "SILVER" in mem or "GOLD_micro" in mem:
        tag = [x for x in ("SILVER", "GOLD_micro", "COPPER", "PLAT", "PALLAD") if x in mem]
        print(f"metals check -> cluster with {tag}")
