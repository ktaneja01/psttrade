"""Pull IDM time series to diagnose undersizing."""
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

# IDM time series from portfolio stage
try:
    idm = system.portfolio.get_instrument_diversification_multiplier()
except AttributeError:
    # try lowercase
    idm = system.portfolio.get_IDM()

idm = idm.dropna()
print(f"\nIDM time series: {len(idm)} observations")
print(f"Range: {idm.index.min().date()} → {idm.index.max().date()}")
print(f"\nStatistics:")
print(f"  Mean:   {idm.mean():.3f}")
print(f"  Median: {idm.median():.3f}")
print(f"  Min:    {idm.min():.3f}")
print(f"  Max:    {idm.max():.3f}")
print(f"  Std:    {idm.std():.3f}")

# Split full vs OOS
idm_pre = idm[idm.index < "2024-01-01"]
idm_oos = idm[idm.index >= "2024-01-01"]
print(f"\nFull-sample (pre-2024): mean {idm_pre.mean():.3f}, last year mean {idm_pre.tail(252).mean():.3f}")
print(f"OOS (2024-2026):         mean {idm_oos.mean():.3f}")
print(f"OOS first half (2024):   mean {idm_oos[idm_oos.index < '2025-01-01'].mean():.3f}")
print(f"OOS second half (2025+): mean {idm_oos[idm_oos.index >= '2025-01-01'].mean():.3f}")

# Yearly
print(f"\nYearly mean IDM:")
for y in sorted(idm.index.year.unique()):
    sub = idm[idm.index.year == y]
    print(f"  {y}: {sub.mean():.3f}  (range {sub.min():.2f} - {sub.max():.2f})")

# Theoretical max (capped at 2.5 in pysystemtrade defaults)
capped_days = (idm >= 2.49).sum()
print(f"\nDays at IDM cap (>=2.49): {capped_days} / {len(idm)} = {100*capped_days/len(idm):.1f}%")
