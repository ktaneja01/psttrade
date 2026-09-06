"""HERC with handcraft-style shrinkage on CLEAN data. Finds optimal K, renders
dendrogram, computes HERC weights (equal-risk per cluster, inverse-variance within).

Pipeline:
1. engine-consistent returns (diff/carry_price) for the live universe
2. correlation -> shrink 50% toward average off-diagonal (handcraft shrinkage)
3. Ward linkage on distance sqrt(0.5(1-shrunk_corr))
4. optimal K via silhouette score sweep
5. HERC: recursive bisection of the tree, allocate risk by inverse-cluster-variance
6. inverse-variance within each leaf cluster
"""
import sys, io, re
import numpy as np, pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster, dendrogram, to_tree
from scipy.spatial.distance import squareform
from sklearn.metrics import silhouette_score
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

# live universe + classes
sig = open("signals.py").read()
b = sig.split("FROZEN_HANDCRAFT_SHRUNK_WEIGHTS = {")[1].split("}")[0]
instruments = [m.group(1) for m in re.finditer(r'"([^"]+)":', b)]
_o = sys.stdout; sys.stdout = io.StringIO()
ns = {}; exec(sig.split("# Build system with dynamic")[0], ns)
sys.stdout = _o
i2c = {i: c for c, insts in ns["asset_classes"].items() for i in insts}

def eret(code):
    adj = pd.to_numeric(pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").iloc[:,0], errors="coerce").dropna().resample("1B").last()
    carry = pd.to_numeric(pd.read_parquet(f"/usr/local/bc_data/futures_multiple_prices/{code}.parquet")["PRICE"], errors="coerce").resample("1B").last().reindex(adj.index).ffill()
    return (adj.diff()/carry.abs()).replace([np.inf,-np.inf],np.nan).rename(code)

R = pd.concat([eret(i) for i in instruments], axis=1)
R = R[R.index >= "2016-01-01"].resample("W").sum()
R = R.loc[:, R.std() > 1e-12]
insts = list(R.columns); n = len(insts)
Rf = R.fillna(0)

# shrunk correlation (handcraft: 50% toward avg off-diagonal)
C = Rf.corr().values
avg = C[~np.eye(n, dtype=bool)].mean()
S = 0.5*C + 0.5*avg; np.fill_diagonal(S, 1.0)
print(f"n={n} instruments, avg corr {avg:.3f} (shrunk 50% toward it)")

D = np.sqrt(np.clip(0.5*(1-S),0,None)); np.fill_diagonal(D,0)
Z = linkage(squareform(D, checks=False), method="ward")

# ---- optimal K via silhouette ----
print("\n=== optimal-K sweep (silhouette on shrunk-corr distance) ===")
best=(None,-1)
for K in range(3,13):
    lab = fcluster(Z, t=K, criterion="maxclust")
    if len(set(lab))<2: continue
    sil = silhouette_score(D, lab, metric="precomputed")
    mark = ""
    if sil>best[1]: best=(K,sil);
    print(f"  K={K:2d}: silhouette {sil:.4f}")
Kbest=best[0]
print(f"\n-> optimal K = {Kbest} (silhouette {best[1]:.4f})")

# ---- HERC weights at optimal K ----
vols = Rf.std()*np.sqrt(52)
def herc_weights(K):
    lab = fcluster(Z, t=K, criterion="maxclust")
    clusters = {c:[insts[i] for i in range(n) if lab[i]==c] for c in sorted(set(lab))}
    # cluster variance (using shrunk corr + vols): inverse-variance across clusters
    cluster_var={}
    for c,mem in clusters.items():
        idx=[insts.index(m) for m in mem]
        v=vols.values[idx]; sub=S[np.ix_(idx,idx)]
        w=np.ones(len(mem))/len(mem)          # equal within for the cluster-risk calc
        cov=np.outer(v,v)*sub
        cluster_var[c]=float(w.dot(cov).dot(w))
    inv=1/np.array([cluster_var[c] for c in clusters]); inv/=inv.sum()
    cluster_alloc=dict(zip(clusters.keys(),inv))
    # within cluster: inverse-variance (inverse vol^2)
    W={}
    for c,mem in clusters.items():
        idx=[insts.index(m) for m in mem]
        iv=1/(vols.values[idx]**2); iv/=iv.sum()
        for m,wi in zip(mem,iv): W[m]=cluster_alloc[c]*wi
    return clusters,cluster_alloc,W
clusters,calloc,W=herc_weights(Kbest)

from collections import Counter
print(f"\n=== HERC clusters at K={Kbest} (cluster risk alloc + members) ===")
for k,c in enumerate(sorted(clusters,key=lambda x:-len(clusters[x])),1):
    mem=clusters[c]; cc=Counter(i2c.get(m,'?') for m in mem)
    print(f"CLUSTER {k} (n={len(mem)}, risk={calloc[c]*100:.1f}%)  [{', '.join(f'{v} {kk}' for kk,v in cc.most_common())}]")
    print(f"   {', '.join(sorted(mem))}")

# dendrogram
fig,ax=plt.subplots(figsize=(22,10))
dendrogram(Z,labels=insts,leaf_rotation=90,leaf_font_size=8,ax=ax,color_threshold=Z[-(Kbest-1),2])
ax.set_title(f"HERC dendrogram (clean data, 50% shrink, Ward). Optimal K={Kbest} (silhouette).")
ax.set_ylabel(r"distance $\sqrt{0.5(1-\rho_{shrunk})}$")
plt.tight_layout(); plt.savefig("/tmp/herc_dendro.png",dpi=110)
print("\nDendrogram -> /tmp/herc_dendro.png")

# paste-ready weights (cap 3%)
def cap(w,cv=0.03):
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
Wc=cap(W)
print(f"\nHERC weights: n={len(Wc)} max={max(Wc.values())*100:.2f}% min={min(Wc.values())*100:.2f}%")
open("/tmp/dict_herc.txt","w").write("FROZEN_HANDCRAFT_SHRUNK_WEIGHTS = {\n"+"".join(f'    "{k}": {v:.6f},\n' for k,v in sorted(Wc.items(),key=lambda x:-x[1]))+"}\n")
