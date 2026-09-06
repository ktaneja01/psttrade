"""Focused breadth backtest: build the live signals.py system (68 instruments),
run the dynamic-optimised portfolio, report overall + per-year Sharpe, return,
realized vol, and dyn-opt FILL RATE per instrument (esp the 10 new breadth names).
Reuses signals.py verbatim via the build seam.
"""
import os
os.environ.setdefault("CAPITAL", "500000")
import io, sys, numpy as np, pandas as pd

# ---- build system exactly as signals.py up to the dyn-opt build ----
src = open("signals.py").read()
# run through the full build incl. the dyn-opt system object, but suppress its prints
prefix = src.split("# Per-instrument × per-rule SR cost")[0]  # stop before heavy diagnostics
ns = {}
_o = sys.stdout; sys.stdout = io.StringIO()
try:
    exec(prefix, ns)
finally:
    sys.stdout = _o
system = ns["system"]
instruments = ns["config"].instruments
NEW = ["EU-BANKS","EU-BASIC","EU-INSURE","EUROSTX-SMALL","US-REALESTATE",
       "FTSECHINAA","MSCISING","IRON","RUBBER","CANOLA"]

print(f"Built system: {len(instruments)} instruments. Running dyn-opt portfolio...\n", flush=True)
pnl = system.accounts.optimised_portfolio()
# percentage daily returns (as_ts is a PROPERTY); .percent() gives % curve
daily_ret = pnl.percent.as_ts.dropna() / 100.0   # percent + as_ts are PROPERTIES; -> fraction of capital/day

def stats(r):
    r = r.dropna()
    if len(r) < 20 or r.std() == 0: return (np.nan, np.nan, np.nan)
    ann = r.mean()*256; vol = r.std()*np.sqrt(256); sr = ann/vol if vol else np.nan
    return sr, ann, vol

cap = 500000.0
sr, ann, vol = stats(daily_ret)
print(f"=== OVERALL (dyn-opt, {len(instruments)} instruments) ===")
print(f"  Sharpe {sr:.3f}   return {ann*100:.1f}%/yr   realized vol {vol*100:.1f}%   "
      f"span {daily_ret.index.min().date()}..{daily_ret.index.max().date()}")

# per-year
print("\n=== PER YEAR ===")
print(f"  {'year':6s}{'P&L$':>12s}{'ret%':>8s}{'vol%':>8s}{'Sharpe':>8s}")
for y, grp in daily_ret.groupby(daily_ret.index.year):
    s, a, v = stats(grp)
    print(f"  {y:<6d}{grp.sum()*cap:>12,.0f}{grp.sum()*100:>8.1f}{v*100:>8.1f}{s:>8.2f}", flush=True)

# fill rate per instrument (fraction of days with a nonzero optimised position)
print("\n=== FILL RATE (share of days with nonzero position) ===")
rows=[]
for inst in instruments:
    try:
        pos = system.accounts.get_optimised_position(inst).dropna()
        fill = (pos != 0).mean() if len(pos) else 0.0
        rows.append((inst, fill, inst in NEW))
    except Exception as e:
        rows.append((inst, np.nan, inst in NEW))
rows.sort(key=lambda x: -(x[1] if x[1]==x[1] else -1))
print("  -- NEW breadth names --")
for inst, fill, isnew in rows:
    if isnew: print(f"    {inst:15s} {fill*100:5.1f}%")
newfills=[f for i,f,n in rows if n and f==f]
print(f"  new-name avg fill: {np.mean(newfills)*100:.1f}%   (>=20% = tradeable)")
allfills=[f for i,f,n in rows if f==f]
print(f"  whole-book avg fill: {np.mean(allfills)*100:.1f}%   |  names <10% fill: {sum(1 for f in allfills if f<0.10)}/{len(allfills)}")
