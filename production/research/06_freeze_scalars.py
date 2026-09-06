"""Stage 6 — freeze forecast scalars on the CURATED store. Deterministic & reproducible.

Runs Carver's SHIPPED pooled scalar estimator (target_abs=10, all-data window,
min_periods=500, backfill) over the 28-rule set, reading the curated store via a
dot-free symlink alias (pysystemtrade's parquet resolver mangles the dotted repo
path). Emits artifacts/forecast_scalars.txt (paste-ready FROZEN_SCALARS dict).

Run:  pst-env/bin/python3 production/research/06_freeze_scalars.py
"""
import os, io, contextlib, re, json
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
os.chdir(ROOT)
CFG = json.load(open(os.path.join(HERE, "config.json")))
CUR = os.path.join(HERE, "data", "curated_rolladjusted")

# dot-free alias for the parquet resolver
ALIAS = "/tmp/curated_store"
if os.path.realpath(ALIAS) != os.path.realpath(CUR):
    if os.path.islink(ALIAS) or os.path.exists(ALIAS):
        os.remove(ALIAS)
    os.symlink(CUR, ALIAS)

os.environ["CAPITAL"] = "500000"
PC = "private/private_config.yaml"
_orig = open(PC).read()
open(PC, "w").write(re.sub(r"parquet_store:.*", f"parquet_store: '{ALIAS}'", _orig))
try:
    src = open("signals.py").read().split(
        "# ============================================================\n# Per-instrument × per-rule SR cost")[0]
    # enable pooled scalar estimation with shipped defaults (deterministic)
    src = src.replace('config.use_forecast_scale_estimates = False',
                      'config.use_forecast_scale_estimates = True\n'
                      'config.forecast_scalar_estimate = dict(pool_instruments=True, '
                      'func="sysquant.estimators.forecast_scalar.forecast_scalar", '
                      'window=250000, min_periods=500, backfill=True)')
    # drop PLN (no raw source in the curated store)
    src = src.replace('config.instrument_weights = FROZEN_HANDCRAFT_SHRUNK_WEIGHTS',
                      'FROZEN_HANDCRAFT_SHRUNK_WEIGHTS.pop("PLN", None); '
                      'config.instrument_weights = FROZEN_HANDCRAFT_SHRUNK_WEIGHTS')
    ns = {}
    with contextlib.redirect_stdout(io.StringIO()):
        exec(src, ns)
    system = ns["system"]; config = ns["config"]
    rules = ns["trend_rules"] + ns["carry_rules"] + ns["skew_rules"]
    inst0 = config.instruments[0]   # pooled -> identical for every instrument
    out = {}
    for r in rules:
        fs = system.forecastScaleCap.get_forecast_scalar(inst0, r)
        out[r] = round(float(pd.Series(fs).dropna().iloc[-1]), 4)
    txt = "FROZEN_SCALARS = {\n" + "".join(f'    "{r}": {out[r]},\n' for r in rules) + "}\n"
    open(os.path.join(HERE, "artifacts", "forecast_scalars.txt"), "w").write(txt)
    print(f"scalars: {len(out)} rules estimated on curated store")
    print("-> artifacts/forecast_scalars.txt")
finally:
    open(PC, "w").write(_orig)
