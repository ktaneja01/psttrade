"""Diagnose which instruments fail the Dynamic Optimization stage."""
import os
os.environ.setdefault("CAPITAL", "1000000")

import numpy as np
import pandas as pd

print("Building system...")
exec(open("signals.py").read().split("# Build system with dynamic optimisation")[0])
from systems.basesystem import System
from systems.provided.dynamic_small_system_optimise.optimised_positions_stage import (
    optimisedPositions,
)
from systems.provided.dynamic_small_system_optimise.accounts_stage import (
    accountForOptimisedStage,
)
system = System(
    [accountForOptimisedStage(), optimisedPositions(), Portfolios(), PositionSizing(),
     myFuturesRawData(), ForecastCombine(), volAttenForecastScaleCap(), Rules()],
    parquetFuturesSimData(), config,
)

# Databento GLBX sources (CME/CBOT/COMEX/NYMEX)
DATABENTO_INSTS = {
    # Bonds/STIR
    "US10", "US30", "US2", "US3", "US5", "US10U", "US20", "SOFR1",
    # Grains (CBOT)
    "REDWHEAT","SOYMEAL","SOYOIL","WHEAT","CORN","SOYBEAN","OATIES","RICE",
    # Energy (NYMEX)
    "CRUDE_W","BRENT_W","GAS_US","GASOILINE","HEATOIL","GAS-LAST",
    # Metals (COMEX)
    "GOLD","SILVER","COPPER","PLAT","PALLAD","STEEL",
    # Equity (CME)
    "SP500","NASDAQ","RUSSELL","DOW","NIKKEI","SP400",
    # FX (CME)
    "EUR","JPY","GBP","AUD","NZD","CHF","CAD","EURCHF","GBPEUR","PLN","EURCAD",
    "MXP","ZAR","BRE","NOK","SEK","GBPJPY",
    # Livestock (CME)
    "LIVECOW","FEEDCOW","LEANHOG",
    # Softs/Ags (CBOT)
    "LUMBER-new",
    # Crypto
    "BITCOIN","ETHEREUM",
}

print(f"\nActive instruments in config: {len(config.instruments)}")
print(f"Databento-sourced among active: {len(set(config.instruments) & DATABENTO_INSTS)}")

results = []
for inst in sorted(config.instruments):
    src = "databento" if inst in DATABENTO_INSTS else "barchart"
    try:
        p = system.accounts.pandl_for_optimised_instrument(inst)
        series = p.as_ts.dropna()
        if len(series) == 0:
            results.append((inst, src, "EMPTY", np.nan, np.nan, 0, 0))
            continue
        # Failure modes
        has_inf = np.isinf(series).any()
        has_nan = series.isna().any()
        all_zero = (series == 0).all()

        ann_mean = series.mean() * 252
        ann_std  = series.std() * np.sqrt(252)
        sharpe   = ann_mean / ann_std if ann_std > 0 else np.nan
        n_nonzero = int((series != 0).sum())
        n_total = len(series)

        status = "OK"
        if has_inf:
            status = "INF"
        elif has_nan:
            status = "NAN"
        elif all_zero:
            status = "ZERO"
        elif np.isnan(sharpe):
            status = "NAN_SR"
        elif ann_std == 0:
            status = "ZEROSTD"
        elif n_nonzero < 20:
            status = f"SPARSE({n_nonzero}/{n_total})"

        results.append((inst, src, status, sharpe, ann_mean, n_nonzero, n_total))
    except Exception as e:
        results.append((inst, src, f"ERR:{type(e).__name__}", np.nan, np.nan, 0, 0))

# Report failures first
print("\n" + "=" * 85)
print("DO-stage failures (inf/nan/zero/sparse)")
print("=" * 85)
fails = [r for r in results if r[2] not in ("OK",) and not r[2].startswith("SPARSE(") or
         (r[2].startswith("SPARSE(") and int(r[2].split("(")[1].split("/")[0]) < 100)]
if not fails:
    print("  (none — all instruments produce valid DO output)")
else:
    print(f"{'Instrument':<14} {'Source':<10} {'Status':<12} {'Sharpe':>8} {'Ann$':>10} {'nonzero/days':>12}")
    for r in fails:
        sr_str = f"{r[3]:+.3f}" if not np.isnan(r[3]) else "nan"
        am_str = f"{r[4]:+.0f}" if not np.isnan(r[4]) else "nan"
        print(f"{r[0]:<14} {r[1]:<10} {r[2]:<12} {sr_str:>8} {am_str:>10} {r[5]}/{r[6]:>5}")

# Summary counts
print("\n" + "=" * 85)
print("Summary by source")
print("=" * 85)
for src in ["databento", "barchart"]:
    sub = [r for r in results if r[1] == src]
    ok = sum(1 for r in sub if r[2] == "OK")
    fail = len(sub) - ok
    print(f"  {src}: {len(sub)} instruments, {ok} OK, {fail} with issues")

# Zero-position instruments
zero_inst = [r for r in results if r[5] == 0]
if zero_inst:
    print(f"\n{'Instruments with 0 nonzero days (dyn-opt never opened a position):':<85}")
    for r in zero_inst:
        print(f"  {r[0]:<14} ({r[1]})")
