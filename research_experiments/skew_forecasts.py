"""Latest skew forecasts (skewabs180, skewabs365, skewrv180, skewrv365)
across all active instruments.
"""
import os
os.environ["CAPITAL"] = "500000"

import numpy as np
import pandas as pd

print("Rebuilding system...")
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

skew_rules = ["skewabs180", "skewabs365", "skewrv180", "skewrv365"]
instruments = sorted(config.instruments)

# Asset class per instrument (pysystemtrade definition — what skewrv uses)
inst_data = pd.read_csv(
    "/Users/kunal.taneja/pysystemtrade/data/futures/csvconfig/instrumentconfig.csv"
).set_index("Instrument")

def latest(inst, rule):
    try:
        f = system.forecastScaleCap.get_capped_forecast(inst, rule).dropna()
        return float(f.iloc[-1]) if len(f) else np.nan
    except Exception:
        return np.nan

rows = []
for inst in instruments:
    vals = {"Instrument": inst, "AssetClass": inst_data.loc[inst, "AssetClass"]}
    for r in skew_rules:
        vals[r] = latest(inst, r)
    vals["avg_skew"] = np.nanmean([vals[r] for r in skew_rules])
    rows.append(vals)

df = pd.DataFrame(rows).sort_values("avg_skew", ascending=False)

print("\n" + "=" * 100)
print("Latest skew forecasts — sorted by avg_skew descending")
print("=" * 100)
hdr = f"{'Instrument':<13} {'Class':<10} {'skewabs180':>10} {'skewabs365':>10} {'skewrv180':>10} {'skewrv365':>10}  {'avg':>6}"
print(hdr)
print("-" * 100)
for _, r in df.iterrows():
    print(f"{r['Instrument']:<13} {r['AssetClass']:<10} "
          f"{r['skewabs180']:>+10.1f} {r['skewabs365']:>+10.1f} "
          f"{r['skewrv180']:>+10.1f} {r['skewrv365']:>+10.1f}  {r['avg_skew']:>+6.1f}")

# Save CSV
df.to_csv("/tmp/skew_forecasts.csv", index=False)

# Aggregates by asset class
print(f"\n{'='*75}")
print("Class average skew-signal direction")
print(f"{'='*75}")
print(f"{'Class':<10} {'#inst':>5} {'mean_skewabs180':>16} {'mean_skewrv180':>16}  {'signal':<30}")
print("-" * 90)
for cls in sorted(df["AssetClass"].unique()):
    sub = df[df.AssetClass == cls]
    mabs = sub["skewabs180"].mean()
    mrv  = sub["skewrv180"].mean()
    signal = "LONG (crash-insurance)" if mabs > 1 else "SHORT (lottery)" if mabs < -1 else "neutral"
    print(f"{cls:<10} {len(sub):>5d} {mabs:>+15.2f} {mrv:>+15.2f}   {signal}")

print(f"\nCSV saved to /tmp/skew_forecasts.csv")
