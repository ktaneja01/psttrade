"""Latest per-rule forecasts across instruments, plus the forecast scalars used.

Outputs:
  1. Trend family forecast matrix (12 rules × 55 instruments, latest values)
  2. Carry family forecast matrix (12 rules × 55 instruments, latest values)
  3. Forecast scalars table per (rule, instrument)
"""
import os
os.environ["CAPITAL"] = "500000"

import numpy as np
import pandas as pd

print("Rebuilding system for forecast-matrix extraction...")
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
     RawData(), ForecastCombine(), volAttenForecastScaleCap(), Rules()],
    parquetFuturesSimData(), config,
)

trend_rules = ["spot_trend8_32", "spot_trend16_64", "spot_trend32_128", "spot_trend64_256",
               "accel8", "accel16", "accel32", "accel64",
               "breakout20", "breakout40", "breakout80", "breakout160"]
carry_rules = ["carry10", "carry30", "carry60", "carry125",
               "relcarry10", "relcarry30", "relcarry60", "relcarry125",
               "carry_accel10", "carry_accel30", "carry_accel60", "carry_accel125"]

instruments = sorted(config.instruments)


def latest_capped(inst, rule):
    try:
        f = system.forecastScaleCap.get_capped_forecast(inst, rule)
        f = f.dropna()
        return float(f.iloc[-1]) if len(f) else np.nan
    except Exception:
        return np.nan


def scalar(inst, rule):
    try:
        s = system.forecastScaleCap.get_forecast_scalar(inst, rule)
        # May be scalar or time series
        if hasattr(s, "iloc"):
            s = s.dropna()
            return float(s.iloc[-1]) if len(s) else np.nan
        return float(s)
    except Exception:
        return np.nan


def print_matrix(title, rules):
    rows = []
    for inst in instruments:
        row = {"instrument": inst}
        for r in rules:
            row[r] = latest_capped(inst, r)
        rows.append(row)
    df = pd.DataFrame(rows).set_index("instrument")
    print(f"\n{'=' * (15 + 7 * len(rules))}")
    print(f"{title} — latest (capped) forecasts")
    print(f"{'=' * (15 + 7 * len(rules))}")
    # Print compact
    short = {r: r.replace("spot_trend", "spt").replace("breakout", "brk")
                  .replace("carry_accel", "c_a").replace("relcarry", "rcar")
             for r in rules}
    hdr = f"{'Instrument':<13}" + " ".join(f"{short[r]:>7}" for r in rules) + "   avg"
    print(hdr)
    print("-" * (13 + 8 * len(rules) + 6))
    for inst in instruments:
        vals = [df.loc[inst, r] for r in rules]
        valid = [v for v in vals if not np.isnan(v)]
        avg = np.mean(valid) if valid else np.nan
        cells = " ".join(f"{v:>+7.1f}" if not np.isnan(v) else f"{'—':>7}" for v in vals)
        print(f"{inst:<13}{cells}   {avg:>+6.2f}" if not np.isnan(avg) else f"{inst:<13}{cells}   {'nan':>6}")
    return df


trend_df = print_matrix("TREND", trend_rules)
carry_df = print_matrix("CARRY", carry_rules)

# Save CSVs for easy inspection
trend_df.to_csv("/tmp/trend_forecasts.csv")
carry_df.to_csv("/tmp/carry_forecasts.csv")

# Forecast scalars: one table (rule × summary stats across instruments)
print(f"\n{'=' * 70}")
print("Forecast scalars — estimated rolling (per-instrument), latest value")
print(f"{'=' * 70}")
print(f"{'Rule':<18} {'mean':>8} {'median':>8} {'min':>8} {'max':>8} {'N':>5}")
print("-" * 70)
for r in trend_rules + carry_rules:
    scalars = [scalar(i, r) for i in instruments]
    scalars = [s for s in scalars if not np.isnan(s)]
    if scalars:
        print(f"{r:<18} {np.mean(scalars):>8.3f} {np.median(scalars):>8.3f} "
              f"{min(scalars):>8.3f} {max(scalars):>8.3f} {len(scalars):>5d}")
    else:
        print(f"{r:<18} {'—':>8} {'—':>8} {'—':>8} {'—':>8} {'0':>5}")

# Save full scalar matrix too
scalar_rows = []
for inst in instruments:
    row = {"instrument": inst}
    for r in trend_rules + carry_rules:
        row[r] = scalar(inst, r)
    scalar_rows.append(row)
pd.DataFrame(scalar_rows).set_index("instrument").to_csv("/tmp/forecast_scalars.csv")

print("\n(Saved detailed matrices to /tmp/trend_forecasts.csv, "
      "/tmp/carry_forecasts.csv, /tmp/forecast_scalars.csv)")
