"""Run the actual handcraft_shrunk algorithm on our 59-instrument universe
and visualize the weight distribution as (1) a horizontal bar chart grouped
by cluster, and (2) a treemap.
"""
import numpy as np
import pandas as pd
from sysquant.estimators.correlations import correlationEstimate
from sysquant.estimators.mean_estimator import meanEstimates
from sysquant.estimators.stdev_estimator import stdevEstimates
from sysquant.estimators.estimates import Estimates
from sysquant.optimisation.optimisers.handcraft import handcraft_optimisation

bad = {'US2','US3','US5','EURCHF','GBPEUR','CAD','SOFR1','LUMBER-new','OATIES','STEEL',
       'BRENT_W','SHATZ','BOBL','COTTON2','SUGAR11','EURIBOR','BTP3','BRENT-LAST','INR',
       'US10U','US20','CAC','DAX','GAS_US','OAT','BUXL','BONO'}
raw = {
    'Bonds': ['US10','US30','BUND','GILT','BTP'],
    'Grains': ['REDWHEAT','SOYMEAL','SOYOIL','WHEAT','CORN','SOYBEAN'],
    'Energy-Livestock': ['CRUDE_W','GASOILINE','HEATOIL','GAS-LAST','LIVECOW','FEEDCOW',
                         'LEANHOG','RICE','GBPJPY','COFFEE','OJ','GASOIL','COCOA'],
    'Equity-Risk': ['SP500','NASDAQ','RUSSELL','DOW','NIKKEI','SP400','EUROSTX','FTSE100',
                    'VIX','V2X','AEX','HANG','SMI','MSCIWORLD'],
    'G10-FX': ['EUR','JPY','GBP','AUD','NZD','CHF','PLN','EURCAD','DX','NOK','SEK'],
    'EM-Metal-Crypto': ['MXP','ZAR','BRE','GOLD','SILVER','COPPER','PLAT','PALLAD','BITCOIN','ETHEREUM'],
}
insts = [i for vs in raw.values() for i in vs]
inst_to_class = {i: c for c, vs in raw.items() for i in vs}

def wkly(c):
    s = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{c}.parquet").squeeze().dropna()
    s = s.resample("1B").last().ffill(); s = s[s>0]
    r = s.pct_change().dropna().replace([np.inf,-np.inf], np.nan).dropna()
    return r.resample("W").sum().rename(c)

rets = pd.concat([wkly(i) for i in insts], axis=1)
rets = rets[rets.index >= "2016-01-01"].dropna(thresh=int(len(insts)*0.5)).fillna(0)

corr = rets.corr()
vols = rets.std()*np.sqrt(52)
means = rets.mean()*52

est = Estimates(
    correlation=correlationEstimate(values=corr.values, columns=list(corr.columns)),
    mean=meanEstimates({i: float(means[i]) for i in insts}),
    stdev=stdevEstimates({i: float(vols[i]) for i in insts}),
    data_length=len(rets), frequency='W',
).shrink_correlation_to_average(0.5)

out = handcraft_optimisation(est, equalise_SR=True, equalise_vols=True)
raw_w = dict(out.weights)

# Apply 5% cap
MAX_W = 0.05
def cap(w, c=MAX_W):
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

weights = cap(raw_w, MAX_W)

# -----------------------------------------------------------------------------
# Visualization
# -----------------------------------------------------------------------------
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Rectangle

CLASS_COLORS = {'Bonds':'#1f77b4','Grains':'#8c564b','Energy-Livestock':'#ff7f0e',
                'Equity-Risk':'#2ca02c','G10-FX':'#9467bd','EM-Metal-Crypto':'#e377c2'}

# ============================================================
# Figure 1: Horizontal bar chart grouped by class
# ============================================================
fig, ax = plt.subplots(figsize=(13, 14))
# Sort by class then by weight
ordered = []
class_boundaries = {}
for cls in raw.keys():
    members = [(i, weights[i]) for i in raw[cls] if i in weights]
    members.sort(key=lambda x: -x[1])  # descending within class
    class_boundaries[cls] = (len(ordered), len(ordered)+len(members))
    ordered.extend([(i, w, cls) for i, w in members])

names = [x[0] for x in ordered]
wts = [x[1]*100 for x in ordered]
cols = [CLASS_COLORS[x[2]] for x in ordered]
y = np.arange(len(names))
ax.barh(y, wts, color=cols, edgecolor='white', linewidth=0.5)
ax.set_yticks(y)
ax.set_yticklabels(names, fontsize=8)
ax.invert_yaxis()
ax.set_xlabel("Weight (%)", fontsize=11)

# Annotate each bar with weight
for i, (w_val, c) in enumerate(zip(wts, cols)):
    ax.text(w_val + 0.03, i, f'{w_val:.2f}%', va='center', fontsize=7, color='gray')

# Draw class separator lines
for cls, (start, end) in class_boundaries.items():
    if start > 0:
        ax.axhline(start - 0.5, color='black', linestyle='-', linewidth=0.5, alpha=0.3)

# Add class totals on the right
ax2 = ax.twinx()
cls_totals = {cls: sum(w for i, w, c in ordered if c == cls) for cls in raw.keys()}
for cls, (start, end) in class_boundaries.items():
    mid = (start + end - 1) / 2
    ax2.text(1.01, 1 - mid / (len(ordered)-1),
             f"{cls}\n{cls_totals[cls]*100:.1f}% total\n({end-start} inst)",
             transform=ax2.transAxes, va='center', fontsize=9, fontweight='bold',
             color=CLASS_COLORS[cls])
ax2.set_yticks([])

ax.set_title(f"Handcraft_shrunk weights — 59 instruments\n"
             f"(50% corr shrinkage, equal-SR, 5% per-instrument cap)",
             fontsize=12)
ax.grid(axis='x', alpha=0.3)

handles = [mpatches.Patch(color=c, label=f"{k} ({cls_totals[k]*100:.1f}%)")
           for k,c in CLASS_COLORS.items()]
ax.legend(handles=handles, loc='lower right', fontsize=9, title='Cluster (% of book)')

plt.tight_layout()
plt.savefig("/tmp/weights_barchart.png", dpi=120)
plt.close()
print("Saved /tmp/weights_barchart.png")

# ============================================================
# Figure 2: Treemap (hierarchical, clusters as blocks)
# ============================================================
try:
    import squarify
    have_squarify = True
except ImportError:
    have_squarify = False

fig, ax = plt.subplots(figsize=(14, 9))

# Two-level treemap: cluster → instrument
if have_squarify:
    sizes = []
    labels = []
    colors = []
    for cls in raw.keys():
        for inst in raw[cls]:
            if inst in weights:
                sizes.append(weights[inst]*100)
                labels.append(f"{inst}\n{weights[inst]*100:.1f}%")
                colors.append(CLASS_COLORS[cls])
    squarify.plot(sizes=sizes, label=labels, color=colors, alpha=0.85,
                  text_kwargs={'fontsize':7}, ax=ax)
else:
    # Fallback: manual 1D treemap with class groupings
    y_pos = 0
    for cls in raw.keys():
        cls_total = cls_totals[cls]
        if cls_total == 0: continue
        members = sorted([(i, weights[i]) for i in raw[cls] if i in weights], key=lambda x:-x[1])
        x_pos = 0
        for inst, w in members:
            rect = Rectangle((x_pos, y_pos), w*100, cls_total*100,
                           facecolor=CLASS_COLORS[cls], edgecolor='white', linewidth=1)
            ax.add_patch(rect)
            if w > 0.008:  # label if big enough
                ax.text(x_pos + w*50, y_pos + cls_total*50, f"{inst}\n{w*100:.1f}%",
                       ha='center', va='center', fontsize=7)
            x_pos += w*100
        ax.text(-1, y_pos + cls_total*50, cls, ha='right', va='center',
               fontsize=10, fontweight='bold', color=CLASS_COLORS[cls])
        y_pos += cls_total*100
    ax.set_xlim(-8, 105)
    ax.set_ylim(0, 100)

ax.set_title(f"Handcraft_shrunk weight distribution — treemap view\n"
             f"(area ∝ portfolio weight)", fontsize=12)
ax.axis('off')
plt.tight_layout()
plt.savefig("/tmp/weights_treemap.png", dpi=120)
plt.close()
print("Saved /tmp/weights_treemap.png")

# ============================================================
# Figure 3: Donut showing cluster totals
# ============================================================
fig, ax = plt.subplots(figsize=(9, 9))
cls_list = list(raw.keys())
cls_wts_list = [cls_totals[c]*100 for c in cls_list]
cls_colors_list = [CLASS_COLORS[c] for c in cls_list]
cls_labels = [f"{c}\n{cls_totals[c]*100:.1f}%\n({sum(1 for i in raw[c] if i in weights)} inst)"
              for c in cls_list]

wedges, texts = ax.pie(cls_wts_list, labels=cls_labels, colors=cls_colors_list,
                        wedgeprops=dict(width=0.4, edgecolor='white', linewidth=2),
                        textprops={'fontsize':10, 'fontweight':'bold'})
ax.set_title("Cluster weight distribution (59-inst handcraft_shrunk)", fontsize=12)
plt.tight_layout()
plt.savefig("/tmp/weights_donut.png", dpi=120)
plt.close()
print("Saved /tmp/weights_donut.png")

# ============================================================
# Text summary
# ============================================================
print(f"\n{'='*70}")
print(f"Handcraft_shrunk weight distribution (post-5%-cap)")
print(f"{'='*70}")
print(f"{'Class':<22} {'#inst':>5} {'Total':>8} {'Avg/inst':>10} {'Max':>8} {'Min':>8}")
print('-'*70)
for cls in raw.keys():
    members = [weights[i] for i in raw[cls] if i in weights]
    if not members: continue
    print(f"{cls:<22} {len(members):>5d} {sum(members)*100:>7.2f}% "
          f"{np.mean(members)*100:>9.3f}% {max(members)*100:>7.2f}% {min(members)*100:>7.3f}%")
print('-'*70)
all_w = list(weights.values())
print(f"{'TOTAL':<22} {len(all_w):>5d} {sum(all_w)*100:>7.2f}% {np.mean(all_w)*100:>9.3f}% "
      f"{max(all_w)*100:>7.2f}% {min(all_w)*100:>7.3f}%")
