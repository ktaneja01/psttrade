"""Second-pass INTUITIVE handcraft.

Refinements applied (from the correlation sanity check):
  - Bonds: collapsed US/Europe -> one global cluster (rates move together).
  - Equity: dropped the weak "Asia" leaf; NIKKEI/HANG folded into one global
    equity Beta group.
  - Vol: promoted to a standalone 7th asset class (was under Equity). Each of
    the 7 classes starts at 1/7 risk; Vol's 1/7 is then capped down to 3%.
  - Energy: flattened Petroleum/GasCarbon -> one cluster (kills the GAS-LAST/EUA
    4.17% spike from a 2-name sub-branch).
  - Crypto: NOT merged/dropped. Kept in Metals but hard-capped at 3% total.
  - Vol: hard-capped at 3% total.

Method: equal-risk-per-branch top-down -> 1/N at leaves -> GROUP caps
(Crypto<=3%, Vol<=3%, redistribute) -> per-instrument 5% cap.
"""
import numpy as np, pandas as pd, re

HIERARCHY = {
    "Ags": {
        "Grains":    ["SOYOIL", "REDWHEAT", "WHEAT", "SOYMEAL", "SOYBEAN", "CORN", "RICE"],
        "Softs":     ["OJ", "COFFEE", "ROBUSTA", "COCOA"],
        "Livestock": ["LEANHOG", "LIVECOW", "FEEDCOW"],
    },
    "Bonds": {                                    # collapsed: rates are global
        "Rates": ["US10", "US30", "IG", "BUND", "GILT", "BTP"],
    },
    "Equity": {
        "Beta": ["SP500", "RUSSELL", "EUROSTX", "FTSE100", "TECDAX", "AEX", "SMI", "NIKKEI", "HANG"],
    },
    "FX": {
        "G10": ["JPY", "CHF", "EUR", "GBP", "NZD", "AUD", "NOK", "SEK", "EURCAD", "GBPJPY"],
        "EM":  ["BRE", "PLN", "MXP", "ZAR"],
    },
    "Metals": {
        "Precious": ["GOLD_micro", "SILVER", "PLAT", "PALLAD"],
        "Base":     ["COPPER", "ALUMINIUM_LME", "ZINC_LME"],
        "Crypto":   ["BITCOIN", "ETHEREUM"],      # capped at 2% (see GROUP_CAPS)
    },
    "Energy": {                                   # flattened
        "All": ["CRUDE_W", "GASOILINE", "GASOIL", "HEATOIL", "GAS-LAST", "EUA"],
    },
    "Vol": {                                      # 7th standalone class, capped 3%
        "Vol": ["VIX", "V2X"],
    },
}
GROUP_CAPS = {}                                   # no group caps — pure 1/N
MAX_W = 0.03                                      # per-instrument cap

inst2sub = {m: (top, sub) for top, subs in HIERARCHY.items() for sub, ms in subs.items() for m in ms}
sub_members = {sub: ms for top, subs in HIERARCHY.items() for sub, ms in subs.items()}
all_insts = list(inst2sub)


def compute_weights(hierarchy):
    """Equal-risk per branch top-down, 1/N at leaves."""
    w = {}
    n_top = len(hierarchy)
    for top, subs in hierarchy.items():
        w_top = 1.0 / n_top
        for sub, members in subs.items():
            w_sub = w_top / len(subs)
            for m in members:
                w[m] = w_sub / len(members)
    return w


def apply_group_caps(w, caps):
    """Cap named subclasses at a total allocation; redistribute freed weight
    proportionally to instruments NOT in any capped group."""
    w = dict(w)
    capped_insts = set()
    freed = 0.0
    for sub, cap_total in caps.items():
        members = sub_members[sub]
        cur = sum(w[m] for m in members)
        if cur > cap_total:
            freed += cur - cap_total
            scale = cap_total / cur
            for m in members:
                w[m] *= scale
        capped_insts.update(members)
    # redistribute freed budget to the rest, proportional to current weight
    rest = {k: v for k, v in w.items() if k not in capped_insts}
    rest_total = sum(rest.values())
    for k in rest:
        w[k] += freed * (rest[k] / rest_total)
    return w


def cap_instruments(raw, cap_v, protect):
    """Per-instrument cap; won't push weight back into protected (group-capped)
    names."""
    w = dict(raw); capped = set(protect)
    while True:
        over = {k: v for k, v in w.items() if v > cap_v and k not in capped}
        if not over: break
        excess = sum(v - cap_v for v in over.values())
        for k in over: w[k] = cap_v; capped.add(k)
        under = {k: v for k, v in w.items() if k not in capped}
        ut = sum(under.values())
        if ut <= 0: break
        for k in under: w[k] += excess * (under[k] / ut)
    tot = sum(w.values())
    return {k: v / tot for k, v in w.items()}


raw = compute_weights(HIERARCHY)
capped_groups = apply_group_caps(raw, GROUP_CAPS)
protected = set(m for sub in GROUP_CAPS for m in sub_members[sub])
weights = cap_instruments(capped_groups, MAX_W, protect=protected)

# ------------------------------------------------------------------ corr for reporting
def weekly_returns(code):
    adj = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").squeeze("columns")
    adj = pd.to_numeric(adj, errors="coerce").dropna().resample("1B").last().ffill()
    carry = pd.read_parquet(f"/usr/local/bc_data/futures_multiple_prices/{code}.parquet")["PRICE"]
    carry = pd.to_numeric(carry, errors="coerce").resample("1B").last().reindex(adj.index).ffill()
    r = (adj.diff() / carry).replace([np.inf, -np.inf], np.nan).dropna()
    return r.resample("W").sum().rename(code)

rets = pd.concat([weekly_returns(i) for i in all_insts], axis=1)
rets = rets[rets.index >= "2016-01-01"].fillna(0)
C = rets.corr()
def intra(members):
    s = C.loc[members, members].values; off = s[~np.eye(len(members), dtype=bool)]
    return off.mean() if len(off) else np.nan

softs = {"OJ", "COFFEE", "ROBUSTA", "COCOA"}
print("=" * 78)
print("INTUITIVE HANDCRAFT (2nd pass) — Crypto cap 2%, Vol cap 3%")
print("=" * 78)
for top, subs in HIERARCHY.items():
    tw = sum(weights[m] for sub in subs for m in subs[sub]) * 100
    print(f"\n### {top}  (total {tw:.2f}%)")
    for sub, members in subs.items():
        sw = sum(weights[m] for m in members) * 100
        cap_tag = f"  [CAP {GROUP_CAPS[sub]*100:.0f}%]" if sub in GROUP_CAPS else ""
        print(f"  {sub:9s} n={len(members)} {sw:5.2f}%  intra-corr {intra(members):+.2f}{cap_tag}")
        for m in members:
            print(f"     {m:14s} {weights[m]*100:5.2f}%{' <== SOFT' if m in softs else ''}")

sig = open("signals.py").read()
blk = sig.split("FROZEN_HANDCRAFT_SHRUNK_WEIGHTS = {")[1].split("}")[0]
cur = {m.group(1): float(m.group(2)) for m in re.finditer(r'"([^"]+)":\s*([0-9.]+)', blk)}
print("\n" + "=" * 78)
print("DIFF vs current frozen — softs, crypto, vol")
print("=" * 78)
for grp in ["OJ", "COFFEE", "ROBUSTA", "COCOA", "BITCOIN", "ETHEREUM", "VIX", "V2X"]:
    print(f"  {grp:10s} {cur.get(grp,0)*100:6.3f}%  ->  {weights[grp]*100:6.3f}%   ({(weights[grp]-cur.get(grp,0))*100:+.3f}%)")
print(f"\n  Crypto total: {sum(weights[m] for m in sub_members['Crypto'])*100:.2f}%   Vol total: {sum(weights[m] for m in sub_members['Vol'])*100:.2f}%")
print(f"  Max weight: {max(weights.values())*100:.2f}%   Min: {min(weights.values())*100:.3f}%   Sum: {sum(weights.values()):.4f}")

print("\n" + "=" * 78)
print("Paste-ready dict:")
print("=" * 78)
print("FROZEN_HANDCRAFT_SHRUNK_WEIGHTS = {")
for i in sorted(weights, key=lambda x: -weights[x]):
    print(f'    "{i}": {weights[i]:.6f},')
print("}")
