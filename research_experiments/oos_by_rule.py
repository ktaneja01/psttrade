"""OOS 2024-2026 Sharpe breakdown by trading rule family."""
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

CAPITAL = int(os.environ["CAPITAL"])
OOS_START = "2024-01-01"

FAMILIES = {
    "TREND":  ["spot_trend8_32", "spot_trend16_64", "spot_trend32_128", "spot_trend64_256",
               "accel8", "accel16", "accel32", "accel64",
               "breakout20", "breakout40", "breakout80", "breakout160"],
    "CARRY":  ["carry10", "carry30", "carry60", "carry125",
               "relcarry10", "relcarry30", "relcarry60", "relcarry125",
               "carry_accel10", "carry_accel30", "carry_accel60", "carry_accel125"],
    "SKEW":   ["skewabs180", "skewabs365", "skewrv180", "skewrv365"],
}

def sharpe(r):
    r = r.dropna()
    if len(r) < 20 or r.std() == 0:
        return np.nan, 0, 0
    ann_mean = r.mean() * 252
    ann_std = r.std() * np.sqrt(252)
    return ann_mean / ann_std, ann_mean, ann_std

rule_results = {}
family_series = {fam: None for fam in FAMILIES}

print("\nComputing per-rule OOS & Full-sample Sharpe...")
for family, rules in FAMILIES.items():
    for rule in rules:
        try:
            p = system.accounts.pandl_for_trading_rule_weighted(rule)
            r_full = p.as_ts.dropna()
            r_oos = r_full[r_full.index >= OOS_START]

            sr_full, am_full, _ = sharpe(r_full)
            sr_oos, am_oos, _ = sharpe(r_oos)

            rule_results[rule] = {
                "family": family,
                "sr_full": sr_full,
                "sr_oos": sr_oos,
                "ann_full": am_full,
                "ann_oos": am_oos,
            }

            # Accumulate family P&L
            if family_series[family] is None:
                family_series[family] = r_full.copy()
            else:
                family_series[family] = family_series[family].add(r_full, fill_value=0)
        except Exception as e:
            rule_results[rule] = {"family": family, "sr_full": np.nan, "sr_oos": np.nan,
                                  "ann_full": 0, "ann_oos": 0, "error": str(e)[:40]}

# Print per-rule table
print("\n" + "=" * 100)
print(f"Per-rule Sharpe breakdown (CAPITAL = ${CAPITAL:,})")
print("=" * 100)
print(f"{'Rule':<22} {'Family':<8} {'SR full':>9} {'SR OOS':>8} {'Ann$ full':>11} {'Ann$ OOS':>11}")
print("-" * 80)
for fam in FAMILIES:
    for rule in FAMILIES[fam]:
        r = rule_results.get(rule, {})
        sr_f = r.get('sr_full', np.nan)
        sr_o = r.get('sr_oos', np.nan)
        am_f = r.get('ann_full', 0)
        am_o = r.get('ann_oos', 0)
        print(f"{rule:<22} {fam:<8} {sr_f:>+9.3f} {sr_o:>+8.3f} {am_f:>+11.0f} {am_o:>+11.0f}")
    print("-" * 80)

# Per-family aggregated table
print("\n" + "=" * 100)
print(f"Per-family aggregated Sharpe — sum of rule P&L streams")
print("=" * 100)
print(f"{'Family':<8} {'# rules':>8} {'SR full':>9} {'SR OOS':>8} {'Ann$ full':>11} {'Ann$ OOS':>11}")
print("-" * 70)
fam_summary = []
for fam, s in family_series.items():
    if s is None:
        continue
    r_full = s.dropna()
    r_oos = r_full[r_full.index >= OOS_START]
    sr_f, am_f, _ = sharpe(r_full)
    sr_o, am_o, _ = sharpe(r_oos)
    n = len(FAMILIES[fam])
    print(f"{fam:<8} {n:>8d} {sr_f:>+9.3f} {sr_o:>+8.3f} {am_f:>+11.0f} {am_o:>+11.0f}")
    fam_summary.append((fam, sr_f, sr_o, am_f, am_o))

# Combined portfolio (sum of all 3 families)
total = None
for s in family_series.values():
    total = s.copy() if total is None else total.add(s, fill_value=0)
if total is not None:
    r_full = total.dropna()
    r_oos = r_full[r_full.index >= OOS_START]
    sr_f, am_f, _ = sharpe(r_full)
    sr_o, am_o, _ = sharpe(r_oos)
    print("-" * 70)
    print(f"{'ALL':<8} {sum(len(v) for v in FAMILIES.values()):>8d} "
          f"{sr_f:>+9.3f} {sr_o:>+8.3f} {am_f:>+11.0f} {am_o:>+11.0f}")

# Rule count by OOS sign
print("\n" + "=" * 100)
print("OOS rule survival (2024-26)")
print("=" * 100)
for fam in FAMILIES:
    oos_sr = [rule_results[r]["sr_oos"] for r in FAMILIES[fam]
              if not np.isnan(rule_results[r].get("sr_oos", np.nan))]
    pos = sum(1 for s in oos_sr if s > 0)
    neg = sum(1 for s in oos_sr if s < 0)
    mean_sr = np.mean(oos_sr) if oos_sr else float("nan")
    print(f"  {fam:<8} positive={pos}/{len(oos_sr)}  mean SR={mean_sr:+.3f}")
