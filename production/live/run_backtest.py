"""Backtest on the LIVE curated store (freshest IBKR-appended data).

Adapted from production/research/07_run_backtest.py. Differences:
  - reads the LIVE curated_rolladjusted store (data to ~2026-09), not the research snapshot
  - trades the LIVE universe (113): drops EURIBOR/SONIA3/WHEAT (not in live IB fetch/map)
    in addition to PLN (as the research runner does)
  - window 2019-01-01 .. 2026-09-09 (uses the fresh live tail)
  - reuses the frozen strategy artifacts (handcraft weights + forecast scalars) from
    production/research/artifacts — the strategy definition is unchanged.

Run:  pst-env/bin/python3 production/live/run_backtest.py [CAP1 CAP2 ...]
      default capitals: 750000 1000000
"""
import os, io, contextlib, re, json, sys
import pandas as pd, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))            # production/live
ROOT = os.path.dirname(os.path.dirname(HERE))                # repo root
ART  = os.path.join(ROOT, "production", "research", "artifacts")
os.chdir(ROOT)

CUR = os.path.join(HERE, "data", "curated_rolladjusted")     # LIVE store
CAPITALS = [int(x) for x in sys.argv[1:]] or [750000, 1000000]
BT_START = pd.Timestamp("2019-01-01")
# Sim to "today" so the fresh IB tail is included. Override with env SIM_CUTOFF=YYYY-MM-DD.
CUTOFF   = pd.Timestamp(os.environ.get("SIM_CUTOFF") or pd.Timestamp.now().normalize())
DROP = ["PLN", "EURIBOR-ICE", "JGB"]   # only true venue-duplicates dropped; GASOIL/US3/US-PROPERTY/CAD5 reverted (dropping them was fill-noise, -0.045 SR head-to-head; Carver keeps distinct instruments)

# Self-heal: auto-drop any instrument with NO adjusted data after BT_START. The skew
# rule (rawdata.skew -> get_daily_percentage_returns) aborts the whole run with
# "No adjusted daily prices for X" on an empty post-start series (e.g. EURIBOR ends
# 2017). Same intent as the notebook's Step-0c quarantine, but computed here so the
# sim reflects only tradeable instruments and never crashes on a dead vendor feed.
import glob as _glob
_empty = []
for _f in _glob.glob(os.path.join(CUR, "futures_adjusted_prices", "*.parquet")):
    _c = os.path.basename(_f)[:-8]
    try:
        _s = pd.to_numeric(pd.read_parquet(_f).iloc[:, 0], errors="coerce").dropna()
        if (_s.index >= BT_START).sum() == 0:
            _empty.append(_c)
    except Exception:
        _empty.append(_c)
if _empty:
    print(f"AUTO-DROP (no data after {BT_START.date()}): {sorted(_empty)}")
    DROP = list(dict.fromkeys(DROP + _empty))

ALIAS = "/tmp/live_curated_store"
if os.path.realpath(ALIAS) != os.path.realpath(CUR):
    if os.path.islink(ALIAS) or os.path.exists(ALIAS):
        os.remove(ALIAS)
    os.symlink(CUR, ALIAS)

# frozen strategy artifacts (stages 5 & 6)
hc = open(os.path.join(ART, "handcraft_weights.txt")).read().strip()
sc = {m.group(1): float(m.group(2)) for m in
      re.finditer(r'"([^"]+)":\s*([0-9.]+)', open(os.path.join(ART, "forecast_scalars.txt")).read())}

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
        # drop the live-excluded instruments (match the research runner's PLN-drop pattern)
        pops = "".join(f'FROZEN_HANDCRAFT_SHRUNK_WEIGHTS.pop("{d}", None); ' for d in DROP)
        src = src.replace('config.instrument_weights = FROZEN_HANDCRAFT_SHRUNK_WEIGHTS',
                          pops + 'config.instrument_weights = FROZEN_HANDCRAFT_SHRUNK_WEIGHTS')
        ns = {}
        with contextlib.redirect_stdout(io.StringIO()):
            exec(src, ns)
        n_inst = len(ns["config"].instruments)
        ts = pd.Series(ns["system"].accounts.optimised_portfolio().as_ts).dropna()
        ts = ts[(ts.index >= BT_START) & (ts.index <= CUTOFF)]
        yearly = {}
        for y, g in ts.groupby(ts.index.year):
            yearly[int(y)] = dict(pnl=round(g.sum(), 0), ret_pct=round(g.sum() / cap * 100, 2),
                                  sharpe=round(g.mean() / g.std() * np.sqrt(252), 3) if g.std() > 0 else None)
        total = dict(pnl=round(ts.sum(), 0), ret_pct=round(ts.sum() / cap * 100, 2),
                     sharpe=round(ts.mean() / ts.std() * np.sqrt(252), 3),
                     ann_vol_pct=round(ts.std() * np.sqrt(252) / cap * 100, 2),
                     n_instruments=n_inst,
                     start=str(ts.index.min().date()), end=str(ts.index.max().date()))
        return dict(yearly=yearly, total=total)
    finally:
        open(PC, "w").write(_orig)

results = {}
for cap in CAPITALS:
    r = run(cap); results[cap] = r
    t = r["total"]
    print(f"\n===== ${cap:,}  (live store, {t['n_instruments']} insts, {t['start']}..{t['end']}) =====")
    print(f"{'Year':6s}{'P&L':>14s}{'Ret%':>9s}{'Sharpe':>9s}")
    for y, d in r["yearly"].items():
        s = f"{d['sharpe']:>9.3f}" if d['sharpe'] is not None else f"{'n/a':>9s}"
        print(f"{y:<6d}{d['pnl']:>14,.0f}{d['ret_pct']:>8.2f}%{s}")
    print(f"{'TOTAL':6s}{t['pnl']:>14,.0f}{t['ret_pct']:>8.2f}%{t['sharpe']:>9.3f}"
          f"   (ann vol {t['ann_vol_pct']:.1f}%)")

json.dump(results, open(os.path.join(HERE, "artifacts", "backtest_results.json"), "w"), indent=2)
print("\n-> production/live/artifacts/backtest_results.json")
