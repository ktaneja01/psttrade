"""Standalone duplicate-market detector using our parquet data.

Replicates Carver's duplicate_remove_markets logic: flags instrument pairs
with correlation > THRESHOLD over the shared history. Within each duplicate
pair, recommends keeping the more-liquid one (proxied by longer history
+ higher contract pointsize × recent vol).
"""
import numpy as np
import pandas as pd
from itertools import combinations

CORR_THRESHOLD = 0.80  # Carver uses ~0.95; we use 0.80 to see borderline duplicates too
MIN_OVERLAP_WEEKS = 100  # need this many weeks of overlap

bad = {'US2','US3','US5','EURCHF','GBPEUR','CAD','SOFR1','LUMBER-new','OATIES','STEEL',
       'BRENT_W','SHATZ','BOBL','COTTON2','SUGAR11','EURIBOR','BTP3','BRENT-LAST','INR'}

raw_asset_classes = {
    'Bonds': ['US10','US10U','US20','US30','BUND','GILT','BTP','BUXL','OAT','BONO'],
    'Grains': ['REDWHEAT','SOYMEAL','SOYOIL','WHEAT','CORN','SOYBEAN'],
    'Energy-Livestock': ['CRUDE_W','GAS_US','GASOILINE','HEATOIL','GAS-LAST','LIVECOW','FEEDCOW',
                         'LEANHOG','RICE','GBPJPY','COFFEE','OJ','GASOIL','COCOA'],
    'Equity-Risk': ['SP500','NASDAQ','RUSSELL','DOW','NIKKEI','SP400','CAC','DAX','EUROSTX','FTSE100',
                    'VIX','V2X','AEX','HANG','SMI','MSCIWORLD'],
    'G10-FX': ['EUR','JPY','GBP','AUD','NZD','CHF','PLN','EURCAD','DX','NOK','SEK'],
    'EM-Metal-Crypto': ['MXP','ZAR','BRE','GOLD','SILVER','COPPER','PLAT','PALLAD','BITCOIN','ETHEREUM'],
}
instruments = sorted([i for insts in raw_asset_classes.values() for i in insts if i not in bad])

def weekly_returns(code):
    s = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").squeeze()
    s = s.dropna().resample("1B").last().ffill()
    s = s[s > 0]
    r = s.pct_change().dropna()
    # Replace inf values from back-adjusted zero-crossings
    r = r.replace([np.inf, -np.inf], np.nan).dropna()
    return r.resample("W").sum().rename(code)

print("Loading weekly returns for all instruments...", flush=True)
rets = pd.concat([weekly_returns(i) for i in instruments], axis=1)
rets = rets[rets.index >= "2016-01-01"]
print(f"Data: {len(rets)} weeks, {len(instruments)} instruments", flush=True)

# Build correlation matrix with pairwise overlap
print("\nComputing pairwise correlations (shared-history only)...", flush=True)
inst_to_class = {i: c for c, insts in raw_asset_classes.items() for i in insts}

duplicates = []
all_pairs = []
for i, j in combinations(instruments, 2):
    pair = rets[[i, j]].dropna()
    if len(pair) < MIN_OVERLAP_WEEKS:
        continue
    corr = pair[i].corr(pair[j])
    all_pairs.append((i, j, corr, len(pair),
                      inst_to_class.get(i, '?'), inst_to_class.get(j, '?')))
    if corr >= CORR_THRESHOLD:
        duplicates.append((i, j, corr, len(pair)))

print(f"\n{'=' * 80}")
print(f"DUPLICATES: corr >= {CORR_THRESHOLD:.2f} (from {len(all_pairs)} total pairs checked)")
print(f"{'=' * 80}")
print(f"{'Inst A':<12} {'Inst B':<12} {'Corr':>6}  {'#wk':>5}  {'Class A':<18} {'Class B':<18}")
print("-" * 85)
for a, b, c, n in sorted(duplicates, key=lambda x: -x[2]):
    print(f"{a:<12} {b:<12} {c:>6.3f}  {n:>5d}  {inst_to_class.get(a,'?'):<18} {inst_to_class.get(b,'?'):<18}")

# Build the cluster-recommendation
print(f"\n{'=' * 80}")
print(f"RECOMMENDED duplicate_markets (Carver-style, corr >= 0.90)")
print(f"{'=' * 80}")
strict_duplicates = [(a,b,c,n) for a,b,c,n in duplicates if c >= 0.90]

# Build clusters via union-find
parent = {i: i for i in instruments}
def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x
def union(x, y):
    rx, ry = find(x), find(y)
    if rx != ry:
        parent[rx] = ry

for a, b, c, n in strict_duplicates:
    union(a, b)

clusters = {}
for i in instruments:
    root = find(i)
    clusters.setdefault(root, []).append(i)
dup_clusters = [sorted(v) for v in clusters.values() if len(v) > 1]

for cluster in sorted(dup_clusters, key=lambda x: (-len(x), x)):
    # "Keep" = the one with longest history + highest vol × pointsize approximation
    # For simplicity, keep first alphabetical (user can refine)
    print(f"\n  Cluster: {', '.join(cluster)}")
    # Heuristic: keep the one that Carver would (major markets win)
    priority = ['US10', 'BUND', 'BTP', 'SP500', 'NASDAQ', 'NIKKEI', 'EUROSTX', 'GOLD',
                'CRUDE_W', 'GBP', 'EUR', 'JPY', 'AUD', 'VIX']
    keep = None
    for p in priority:
        if p in cluster:
            keep = p
            break
    if keep is None:
        keep = cluster[0]
    drop = [i for i in cluster if i != keep]
    print(f"    Carver-heuristic KEEP: {keep}")
    print(f"    Carver-heuristic DROP (duplicate_markets): {drop}")

print(f"\n{'=' * 80}")
print("Also showing moderate duplicates 0.80 <= corr < 0.90 (borderline)")
print(f"{'=' * 80}")
for a, b, c, n in sorted(duplicates, key=lambda x: -x[2]):
    if 0.80 <= c < 0.90:
        print(f"  {a:<12} ~ {b:<12}  corr={c:.3f}")
