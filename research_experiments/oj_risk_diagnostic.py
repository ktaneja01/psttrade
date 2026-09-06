"""Measure OJ's realized risk leakage through 2025:
  1. vol attenuation multiplier (did it ever fire?)
  2. absolute annualized vol
  3. continuous target position (pre-integer, from position sizing)
  4. optimised INTEGER position (post dyn-opt rounding)
  5. per-instrument risk share = |position * per_contract_value * instr_vol| / capital
Reuses the live system built in signals.py (pre-diagnostic-print seam).
"""
import numpy as np
import pandas as pd

# Build the live system exactly as signals.py does, stopping before its prints.
src = open("signals.py").read().split("# ===")[0]  # stop before diagnostic section
# ensure the System(...) build is included: signals builds it before the "# ==="
# section headers. If not present, fall back to the dyn-opt seam.
if "system = System(" not in src:
    src = open("signals.py").read().split("# Per-instrument")[0]
ns = {}
exec(src, ns)
system = ns["system"]
INST = "OJ"

print("Building OJ diagnostics (this reuses the full live system)...")

# --- 1. attenuation multiplier ---
atten = system.forecastScaleCap.get_vol_attenuation(INST)

# --- 2. absolute daily % vol -> annualized ---
daily_vol = system.rawdata.get_daily_percentage_volatility(INST)   # in price %/100 units
ann_vol = daily_vol * np.sqrt(256)

# --- 3. continuous target position (subsystem, pre-portfolio-weight/opt) ---
subsys = system.positionSize.get_subsystem_position(INST)

# --- 4. optimised integer position ---
opt_pos = system.accounts.get_optimised_position(INST)

# --- 5. per-contract value as proportion of capital ---
pcv_df = system.optimisedPositions.get_per_contract_value_as_proportion_of_capital_df()
pcv = pcv_df[INST] if INST in pcv_df.columns else None

capital = system.config.notional_trading_capital

# Align to a common daily index over 2024-2025 window for reporting
def dly(s):
    return s.resample("1B").last()

atten_d = dly(atten)
annvol_d = dly(ann_vol)
subsys_d = dly(subsys)
opt_d = dly(opt_pos)
pcv_d = dly(pcv) if pcv is not None else None

# realized risk share of capital from the integer position
if pcv_d is not None:
    notional_frac = (opt_d.reindex(annvol_d.index).ffill()
                     * pcv_d.reindex(annvol_d.index).ffill())
    risk_share = (notional_frac.abs() * annvol_d)   # annualized $risk / capital
else:
    risk_share = None

def stats(s, name, pct=False):
    s = s.dropna()
    w = s[(s.index >= "2025-01-01") & (s.index < "2026-01-01")]
    mul = 100 if pct else 1
    print(f"\n{name}")
    print(f"  full sample: mean={s.mean()*mul:.3f}  min={s.min()*mul:.3f}  max={s.max()*mul:.3f}")
    if len(w):
        print(f"  2025 only : mean={w.mean()*mul:.3f}  min={w.min()*mul:.3f}  max={w.max()*mul:.3f}")

print("\n" + "="*70)
print(f"OJ RISK DIAGNOSTIC  (capital=${capital:,})")
print("="*70)
stats(atten_d, "1. Vol attenuation multiplier (1.0=neutral, <1 cut, >1 boost)")
stats(annvol_d, "2. Absolute annualized vol", pct=True)
stats(subsys_d, "3. Continuous subsystem target position (contracts)")
stats(opt_d, "4. Optimised INTEGER position (contracts)")
if risk_share is not None:
    stats(risk_share, "5. Realized risk share (annualized $risk / capital)", pct=True)

# How often does attenuation actually cut (<0.95) vs boost (>1.05)?
a = atten_d.dropna()
print(f"\nAttenuation regime (full sample, n={len(a)}):")
print(f"  cut  (<0.95): {100*(a<0.95).mean():.1f}% of days")
print(f"  neutral     : {100*((a>=0.95)&(a<=1.05)).mean():.1f}% of days")
print(f"  boost (>1.05): {100*(a>1.05).mean():.1f}% of days")

# Rounding lump: how much risk does ONE contract represent, late 2025?
if pcv_d is not None:
    recent = annvol_d.dropna().index[annvol_d.dropna().index < "2026-01-01"][-1]
    one_contract_risk = abs(pcv_d.reindex([recent], method="ffill").iloc[0]
                            * annvol_d.reindex([recent], method="ffill").iloc[0])
    print(f"\nRounding lump (as of {recent.date()}): ONE OJ contract "
          f"= {one_contract_risk*100:.2f}% of capital in annualized risk")
    print(f"  (target continuous position then = {subsys_d.reindex([recent], method='ffill').iloc[0]:.2f} contracts, "
          f"integer held = {opt_d.reindex([recent], method='ffill').iloc[0]:.0f})")
