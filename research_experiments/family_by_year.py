"""Portfolio + trend/carry/skew family P&L by year, using the live signals.py build."""
import sys, io, numpy as np, pandas as pd
raw = open("signals.py").read()
src = raw.split('print("\\n\\n=== Per-instrument Sharpe')[0]
_o = sys.stdout; sys.stdout = io.StringIO()
ns = {}; exec(src, ns)
sys.stdout = _o
system = ns["system"]; instruments = ns["instruments"]
trend_rules = ns["trend_rules"]; carry_rules = ns["carry_rules"]; skew_rules = ns["skew_rules"]

p = system.accounts.optimised_portfolio().as_ts
print(f"PORTFOLIO  Sharpe={p.mean()/p.std()*np.sqrt(256):.3f}  ann=${p.mean()*256:,.0f}  vol=${p.std()*np.sqrt(256):,.0f}")
print("\n=== Total optimised P&L by year ===")
for d, v in p.resample("A").sum().items():
    print(f"  {d.year}: {v:+,.0f}")

fam = {"Trend": trend_rules, "Carry": carry_rules, "Skew": skew_rules}
fam_ts = {}
for name, rules in fam.items():
    agg = None
    for inst in instruments:
        for r in rules:
            try:
                fp = system.accounts.pandl_for_instrument_forecast(inst, r).as_ts
            except Exception:
                continue
            agg = fp.copy() if agg is None else agg.add(fp, fill_value=0)
    fam_ts[name] = agg.dropna()

years = sorted({d.year for d in p.index})
print("\n=== Family Sharpe by year (forecast-level) ===")
print(f"{'Family':7s} " + "".join(f"{y:>7d}" for y in years) + f"{'FULL':>8s}")
for name, ts in fam_ts.items():
    row = f"{name:7s} "
    for y in years:
        w = ts[ts.index.year == y]
        sr = (w.mean()/w.std()*np.sqrt(256)) if w.std() > 0 else 0
        row += f"{sr:+7.2f}"
    full = ts.mean()/ts.std()*np.sqrt(256)
    print(row + f"{full:+8.2f}")

print("\n=== Family P&L $ by year (forecast-level) ===")
print(f"{'Family':7s} " + "".join(f"{y:>9d}" for y in years))
for name, ts in fam_ts.items():
    row = f"{name:7s} "
    for y in years:
        row += f"{ts[ts.index.year==y].sum():>9,.0f}"
    print(row)
