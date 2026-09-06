"""Stage 7 — backtest on the curated store using the frozen artifacts.

Consumes: curated_rolladjusted store (via dot-free alias) + artifacts/handcraft_weights.txt
+ artifacts/forecast_scalars.txt (stages 5 & 6). Runs signals.py's dyn-opt system with
those frozen inputs, P&L window backtest_start..cutoff, dropping PLN. Prints per-year
P&L / return / Sharpe for each capital and writes artifacts/backtest_results.json.

Reproduces the validated 2018-2025 result: 250K SR ~0.474, 500K SR ~0.602.

Run:  pst-env/bin/python3 production/research/07_run_backtest.py [CAP1 CAP2 ...]
      default capitals: 250000 500000
"""
import os, io, contextlib, re, json, sys
import pandas as pd, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
os.chdir(ROOT)
CFG = json.load(open(os.path.join(HERE, "config.json")))
CUR = os.path.join(HERE, "data", "curated_rolladjusted")
CAPITALS = [int(x) for x in sys.argv[1:]] or [250000, 500000]
BT_START = pd.Timestamp(CFG["window"]["backtest_start"])
CUTOFF = pd.Timestamp(CFG["window"]["cutoff"])

ALIAS = "/tmp/curated_store"
if os.path.realpath(ALIAS) != os.path.realpath(CUR):
    if os.path.islink(ALIAS) or os.path.exists(ALIAS):
        os.remove(ALIAS)
    os.symlink(CUR, ALIAS)

# frozen artifacts
hc = open(os.path.join(HERE, "artifacts", "handcraft_weights.txt")).read().strip()
sc = {m.group(1): float(m.group(2)) for m in
      re.finditer(r'"([^"]+)":\s*([0-9.]+)', open(os.path.join(HERE, "artifacts", "forecast_scalars.txt")).read())}

def run(cap):
    os.environ["CAPITAL"] = str(cap)
    PC = "private/private_config.yaml"
    _orig = open(PC).read()
    open(PC, "w").write(re.sub(r"parquet_store:.*", f"parquet_store: '{ALIAS}'", _orig))
    try:
        src = open("signals.py").read().split(
            "# ============================================================\n# Per-instrument × per-rule SR cost")[0]
        # swap in the frozen handcraft weights (artifact)
        src = re.sub(r"FROZEN_HANDCRAFT_SHRUNK_WEIGHTS = \{.*?\n\}", hc, src, count=1, flags=re.DOTALL)
        # swap in the frozen scalars (artifact) across all scalar dicts
        for r, v in sc.items():
            src = re.sub(rf'("{r}":\s*)[0-9.]+', rf'\g<1>{v:.4f}', src)
        # drop PLN
        src = src.replace('config.instrument_weights = FROZEN_HANDCRAFT_SHRUNK_WEIGHTS',
                          'FROZEN_HANDCRAFT_SHRUNK_WEIGHTS.pop("PLN", None); '
                          'config.instrument_weights = FROZEN_HANDCRAFT_SHRUNK_WEIGHTS')
        ns = {}
        with contextlib.redirect_stdout(io.StringIO()):
            exec(src, ns)
        ts = pd.Series(ns["system"].accounts.optimised_portfolio().as_ts).dropna()
        ts = ts[(ts.index >= BT_START) & (ts.index <= CUTOFF)]
        yearly = {}
        for y, g in ts.groupby(ts.index.year):
            yearly[int(y)] = dict(pnl=round(g.sum(), 0), ret_pct=round(g.sum() / cap * 100, 2),
                                  sharpe=round(g.mean() / g.std() * np.sqrt(252), 3) if g.std() > 0 else None)
        total = dict(pnl=round(ts.sum(), 0), ret_pct=round(ts.sum() / cap * 100, 2),
                     sharpe=round(ts.mean() / ts.std() * np.sqrt(252), 3))
        return dict(yearly=yearly, total=total)
    finally:
        open(PC, "w").write(_orig)

results = {}
for cap in CAPITALS:
    r = run(cap); results[cap] = r
    print(f"\n===== ${cap:,} =====")
    print(f"{'Year':6s}{'P&L':>14s}{'Ret%':>9s}{'Sharpe':>9s}")
    for y, d in r["yearly"].items():
        print(f"{y:<6d}{d['pnl']:>14,.0f}{d['ret_pct']:>8.2f}%{d['sharpe']:>9.3f}")
    print(f"{'TOTAL':6s}{r['total']['pnl']:>14,.0f}{r['total']['ret_pct']:>8.2f}%{r['total']['sharpe']:>9.3f}")

json.dump(results, open(os.path.join(HERE, "artifacts", "backtest_results.json"), "w"), indent=2)
print("\n-> artifacts/backtest_results.json")
