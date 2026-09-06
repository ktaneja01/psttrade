import os
"""Data-quality gate for the price store. Run before any backtest.

Catches the failure modes that the single-digit-year mis-dating bug produced
(and slipped through undetected): phantom/mis-dated contract files, multi-year
blobs, implausible price jumps, bad rolls, broken/empty series, wrong price
scale, and economically-impossible cross-correlations (e.g. SILVER vs GOLD ~0).

Usage:
    python data_quality_gate.py                 # check full live universe
    python data_quality_gate.py SILVER GOLD_micro
"""
import sys, os, glob, re
import numpy as np
import pandas as pd

# Store root: override with env DQ_STORE (e.g. the curated backtest store); default = live store.
_STORE = os.environ.get("DQ_STORE", "/usr/local/bc_data")
ADJ = _STORE + "/futures_adjusted_prices/{}.parquet"
MULT = _STORE + "/futures_multiple_prices/{}.parquet"
CONTRACT_DIR = _STORE + "/futures_contract_prices"
START = "2018-01-01"

# Per-instrument daily-move threshold (%). Volatile names get a wider band so a
# real crisis move (2020 crude, VIX spike) is not flagged; tight names catch
# corruption early. Fallback default applies to anything unlisted.
MOVE_THRESH = {
    "CRUDE_W": 0.35, "GAS-LAST": 0.40, "GASOIL": 0.40, "GASOILINE": 0.40,
    "HEATOIL": 0.40, "BITCOIN": 0.30, "ETHEREUM": 0.35, "VIX": 0.50, "V2X": 0.50,
    "EUA": 0.35, "OJ": 0.25, "COFFEE": 0.25, "ROBUSTA": 0.25, "COCOA": 0.25,
    "LEANHOG": 0.20, "LIVECOW": 0.15, "FEEDCOW": 0.15, "SILVER": 0.20, "PALLAD": 0.20,
}
DEFAULT_MOVE = 0.18
# plausible price-scale bands (front-month level) — catches wrong-scale/garbage
SCALE = {
    "SILVER": (10, 60), "GOLD_micro": (900, 4000), "COPPER": (150, 600),
    "PLAT": (500, 2000), "PALLAD": (500, 4000), "CRUDE_W": (-50, 200),
    "LEANHOG": (30, 140), "LIVECOW": (80, 260), "SP500": (1500, 9000),
}
# economically-required correlation pairs (min |rho|, sign)
CORR_PAIRS = [
    ("GOLD_micro", "SILVER", 0.40, +1),
    ("US10", "US30", 0.70, +1),
    ("SP500", "RUSSELL", 0.60, +1),
    ("VIX", "SP500", 0.30, -1),
    ("COFFEE", "ROBUSTA", 0.30, +1),
    ("CRUDE_W", "HEATOIL", 0.50, +1),
    ("EUR", "CHF", 0.40, +1),
]


def live_universe():
    sig = open(os.path.join(os.path.dirname(__file__),"..","signals.py")).read()
    b = sig.split("FROZEN_HANDCRAFT_SHRUNK_WEIGHTS = {")[1].split("}")[0]
    return [m.group(1) for m in re.finditer(r'"([^"]+)":', b)]


def adj_series(code):
    p = ADJ.format(code)
    if not os.path.exists(p):
        return None
    s = pd.to_numeric(pd.read_parquet(p).iloc[:, 0], errors="coerce").dropna()
    return s.resample("1B").last().dropna()


def engine_returns(code):
    """Engine-consistent returns: diff(adjusted) / carry_price. NEVER diff/level
    or pct_change on the adjusted level — the panama-adjusted level can sit near
    zero / go negative for backwardated series (energy, softs), which makes
    level-based returns explode into false 100%+ 'moves'. The engine always
    normalises by the raw carry price, which is strictly positive."""
    adj = adj_series(code)
    if adj is None:
        return None
    p = MULT.format(code)
    if not os.path.exists(p):
        return None
    carry = pd.to_numeric(pd.read_parquet(p)["PRICE"], errors="coerce")
    carry = carry.resample("1B").last().reindex(adj.index).ffill()
    return (adj.diff() / carry.abs()).replace([np.inf, -np.inf], np.nan)


def check_contract_files(code):
    """Contract-integrity: no 200X-dated (for post-2013 names), no multi-year blobs."""
    issues = []
    fs = [f for f in glob.glob(f"{CONTRACT_DIR}/{code}#*.parquet") if "@" not in os.path.basename(f)]
    n200x = sum(1 for f in fs if re.search(r"#20(0[5-9]|1[0-3])", os.path.basename(f)))
    if n200x:
        issues.append(f"{n200x} pre-2014-dated contract files (mis-dating)")
    blobs = 0
    for f in fs:
        try:
            df = pd.read_parquet(f)
            if len(df) and (df.index.max() - df.index.min()).days > 550:
                blobs += 1
        except Exception:
            pass
    if blobs:
        issues.append(f"{blobs} multi-year-blob contract files (>550d span)")
    return issues


def check_series(code):
    issues = []
    s = adj_series(code)
    if s is None:
        return ["NO adjusted-price file"]
    sw = s[s.index >= START]
    if len(sw) < 200:
        issues.append(f"THIN: {len(sw)} obs since {START}")
    # freshness — min acceptable end date (override for a cutoff backtest store via DQ_MIN_END)
    _min_end = pd.Timestamp(os.environ.get("DQ_MIN_END", "2026-01-01"))
    if s.index.max() < _min_end:
        issues.append(f"STALE: ends {s.index.max().date()}")
    # move magnitude — use ENGINE-CONSISTENT returns (diff/carry_price), not
    # diff/level, so backwardated/near-zero panama series don't false-positive.
    thr = MOVE_THRESH.get(code, DEFAULT_MOVE)
    er = engine_returns(code)
    if er is not None:
        r = er.abs().dropna()
        big = r[r > thr]
        if len(big) > 2:
            issues.append(f"{len(big)} moves > {thr*100:.0f}% (worst {r.max()*100:.0f}% on {r.idxmax().date()})")
    # scale
    if code in SCALE:
        lo, hi = SCALE[code]
        med = float(s[s.index >= "2020-01-01"].median())
        if not (lo <= med <= hi):
            issues.append(f"SCALE off: median {med:.1f} outside [{lo},{hi}]")
    return issues


def check_correlations(universe):
    print("\n=== cross-instrument correlation sanity ===")
    rets = {}
    for c in set([p for pr in CORR_PAIRS for p in pr[:2]]):
        er = engine_returns(c)
        if er is not None:
            rets[c] = er
    for a, b, minrho, sign in CORR_PAIRS:
        if a not in rets or b not in rets:
            print(f"  {a}-{b}: MISSING"); continue
        j = pd.concat([rets[a].rename("a"), rets[b].rename("b")], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
        if len(j) < 100:
            print(f"  {a}-{b}: too few obs ({len(j)})"); continue
        rho = j["a"].corr(j["b"])
        ok = (rho * sign) >= minrho
        print(f"  {a}-{b}: rho={rho:+.2f} (need {'+' if sign>0 else '-'}{minrho:.2f})  {'OK' if ok else '<<< ANOMALY'}")


def main():
    universe = sys.argv[1:] if len(sys.argv) > 1 else live_universe()
    print(f"Data-quality gate: {len(universe)} instruments\n")
    bad = {}
    for code in sorted(universe):
        issues = check_contract_files(code) + check_series(code)
        if issues:
            bad[code] = issues
    if bad:
        print("=== INSTRUMENTS WITH ISSUES ===")
        for code, iss in bad.items():
            print(f"  {code}:")
            for i in iss:
                print(f"      - {i}")
    else:
        print("All instruments passed series + contract checks.")
    check_correlations(universe)
    print(f"\n{len(bad)}/{len(universe)} instruments flagged.")


if __name__ == "__main__":
    main()
