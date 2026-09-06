"""Re-estimate pooled forecast scalars on the CLEAN (repaired) data and compare
to the FROZEN_SCALARS in signals.py. Frozen values were computed on the
mis-dated/blobbed data, so this checks how much the corruption moved them.
"""
import os
os.environ["CAPITAL"] = "500000"
import re, numpy as np, pandas as pd

# build the system exactly as signals.py, but turn ESTIMATION ON with pooling
src = open("signals.py").read().split("# Build system with dynamic optimisation")[0]
ns = {}
exec(src, ns)
config = ns["config"]
# flip to estimated + pooled
config.use_forecast_scale_estimates = True
config.forecast_scalar_estimate = {
    "pool_instruments": True,
    "func": "sysquant.estimators.forecast_scalar.forecast_scalar",
    "window": 250000, "min_periods": 500, "backfill": True,
}
from systems.basesystem import System
from systems.forecasting import Rules
from systems.rawdata import RawData
from systems.provided.rob_system.rawdata import myFuturesRawData
from systems.forecast_combine import ForecastCombine
from systems.provided.attenuate_vol.vol_attenuation_forecast_scale_cap import volAttenForecastScaleCap
from systems.positionsizing import PositionSizing
from systems.portfolio import Portfolios
sysd = ns["parquetFuturesSimData"]()
system = System(
    [Portfolios(), PositionSizing(), myFuturesRawData(), ForecastCombine(),
     volAttenForecastScaleCap(), Rules()],
    sysd, config,
)

frozen = ns["FROZEN_SCALARS"]
insts = config.instruments

print("Re-estimating pooled scalars on CLEAN data (this takes a bit)...\n")
print(f"{'rule':16s}{'FROZEN':>10s}{'CLEAN-est':>11s}{'%diff':>8s}{'source':>10s}")
skew_rules = {"skewabs180","skewabs365","skewrv180","skewrv365"}
rows=[]
for rule in frozen:
    # pooled scalar: estimated series is identical across instruments; grab from first instrument that has it
    val=None
    for inst in insts:
        try:
            s = system.forecastScaleCap.get_forecast_scalar(inst, rule)
            v = float(s.iloc[-1]) if hasattr(s,"iloc") else float(s)
            if v==v and v>0: val=v; break
        except Exception:
            continue
    if val is None:
        print(f"{rule:16s}{frozen[rule]:>10.3f}{'—':>11s}"); continue
    fz=frozen[rule]; pct=(val/fz-1)*100
    src_lbl="CARVER" if rule in skew_rules else "self"
    flag="  <<<" if abs(pct)>15 else ""
    print(f"{rule:16s}{fz:>10.3f}{val:>11.3f}{pct:>+7.0f}%{src_lbl:>10s}{flag}")
    rows.append((rule,fz,val,pct))
print("\n(>15% diff flagged — scalar materially changed on clean data)")
# summary
big=[r for r in rows if abs(r[3])>15]
print(f"\n{len(big)}/{len(rows)} scalars moved >15%. Frozen dict to paste (clean):")
print("FROZEN_SCALARS_CLEAN = {")
for rule,fz,val,pct in rows:
    print(f'    "{rule}": {val:.3f},')
print("}")
