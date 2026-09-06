"""Compute handcraft_shrunk weights on full-sample returns and print as Python dict.

Approach: same returns/correlation/vol estimates that signals.py uses, but
computed ONCE on the full sample (not walk-forward). Output is a frozen dict
we can paste into signals.py and run with use_instrument_weight_estimates=False.
"""
import numpy as np
import pandas as pd

from sysquant.estimators.correlations import correlationEstimate
from sysquant.estimators.mean_estimator import meanEstimates
from sysquant.estimators.stdev_estimator import stdevEstimates
from sysquant.estimators.estimates import Estimates
from sysquant.optimisation.optimisers.handcraft import handcraft_optimisation

# Universe imported DIRECTLY from signals.py's live asset_classes (post-bad_markets)
# so the freeze universe can never drift from the traded one. We exec only the
# prefix of signals.py up to the asset_classes definition (before the heavy
# system build) and read `asset_classes` out of that namespace.
import io as _io, sys as _sys
_src = open("signals.py").read().split("N_TARGET_CLASSES")[0]
_ns = {}
_stdout = _sys.stdout; _sys.stdout = _io.StringIO()
try:
    exec(_src, _ns)
finally:
    _sys.stdout = _stdout
_raw = _ns["asset_classes"]          # already has signals.py bad_markets removed
bad_markets = set()                  # exclusions already applied upstream
instruments = [i for insts in _raw.values() for i in insts]

# Weekly % returns, computed the SAME way the engine does: adjusted-price
# DIFFERENCE divided by the raw front-contract (carry) price, never pct_change on
# the adjusted LEVEL. The panama-adjusted level can be negative/low for long
# contango/backwardation histories (e.g. energy) — that's fine, the level is
# never used; diffs are offset-invariant and the carry price is always positive.
# Mirrors rawdata.daily_denominator_price -> get_instrument_raw_carry_data().PRICE.
def weekly_returns(code):
    adj = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").squeeze("columns")
    adj = pd.to_numeric(adj, errors="coerce").dropna().resample("1B").last().ffill()
    carry = pd.read_parquet(f"/usr/local/bc_data/futures_multiple_prices/{code}.parquet")["PRICE"]
    carry = pd.to_numeric(carry, errors="coerce").resample("1B").last().reindex(adj.index).ffill()
    r = (adj.diff() / carry).replace([np.inf, -np.inf], np.nan).dropna()
    return r.resample("W").sum().rename(code)

rets = pd.concat([weekly_returns(i) for i in instruments], axis=1)
rets = rets[rets.index >= "2016-01-01"].dropna(thresh=int(len(instruments) * 0.5)).fillna(0)  # full history (clean data); newer instruments contribute their available span

# Build estimates
corr_df = rets.corr()
vol_series = rets.std() * np.sqrt(52)     # weekly → annual
mean_series = rets.mean() * 52

mean = meanEstimates({i: float(mean_series[i]) for i in instruments})
stdev = stdevEstimates({i: float(vol_series[i]) for i in instruments})
corr = correlationEstimate(values=corr_df.values, columns=list(corr_df.columns))

estimates = Estimates(
    correlation=corr,
    mean=mean,
    stdev=stdev,
    data_length=len(rets),
    frequency="W",
)

# Apply 50% correlation shrinkage toward average
estimates = estimates.shrink_correlation_to_average(0.5)

# Handcraft with equalise_SR=True + equalise_vols=True (matching signals.py config)
out = handcraft_optimisation(estimates, equalise_SR=True, equalise_vols=True)
raw_weights = dict(out.weights)

# Apply same 5% cap logic as signals.py.
# Iteratively cap names above the ceiling and redistribute the excess to names
# still strictly below it. Once a name is capped it is FROZEN (added to `capped`)
# so it can never receive redistribution — otherwise a just-capped name (== cap_v)
# would be treated as "under" and pushed back over the cap forever (infinite loop).
MAX_W = 0.05
def cap(raw, cap_v):
    w = dict(raw)
    capped = set()
    while True:
        over = {k: v for k, v in w.items() if v > cap_v and k not in capped}
        if not over:
            break
        excess = sum(v - cap_v for v in over.values())
        for k in over:
            w[k] = cap_v
            capped.add(k)
        # redistribute only to names strictly below the cap and not yet frozen
        under = {k: v for k, v in w.items() if k not in capped}
        under_total = sum(under.values())
        if under_total <= 0:
            break
        for k in under:
            w[k] += excess * (under[k] / under_total)
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}

frozen = cap(raw_weights, MAX_W)

# Print summary + Python dict
inst_to_class = {i: c for c, insts in _raw.items() for i in insts}
print("=" * 80)
print("FROZEN handcraft_shrunk weights (full-sample, 50% corr shrinkage, equal-SR)")
print("=" * 80)
for cls in _raw:
    members = [i for i in instruments if inst_to_class[i] == cls]
    if not members:
        continue
    cls_total = sum(frozen[i] for i in members) * 100
    print(f"\n{cls}  (n={len(members)}, total={cls_total:.2f}%)")
    for i in sorted(members, key=lambda x: -frozen[x]):
        v = vol_series[i] * 100
        w = frozen[i] * 100
        print(f"  {i:12s}  vol={v:5.1f}%  weight={w:5.2f}%")

print(f"\nTotal: {sum(frozen.values()):.4f}  |  {len(frozen)} instruments")
print(f"Max weight: {max(frozen.values())*100:.2f}%  |  Min: {min(frozen.values())*100:.3f}%")

print("\n" + "=" * 80)
print("Paste into signals.py:")
print("=" * 80)
print("FROZEN_HANDCRAFT_SHRUNK_WEIGHTS = {")
for i in sorted(frozen, key=lambda x: -frozen[x]):
    print(f'    "{i}": {frozen[i]:.6f},')
print("}")
