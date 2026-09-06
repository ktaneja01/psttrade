"""Per-strategy (per-rule) analysis: ann mean, median, skew, and within-group correlations.

For each of the 24 rules in our config, compute the aggregated portfolio-level
P&L (summing instrument-weighted per-instrument-per-rule P&L). Then report:
- Ann mean $, median daily $, skew, Sharpe
- Correlation matrix within trend family (ewmac / accel / breakout)
- Correlation matrix within carry family (carry / relcarry / carry_accel)
"""
import numpy as np
import pandas as pd
from scipy.stats import skew as scipy_skew

# Import signals.py which builds the system + runs backtest
print("Running signals.py to build system...")
from signals import system, instruments, instrument_weights, trend_rules, carry_rules  # noqa: E402

rule_names = trend_rules + carry_rules
print(f"\nRules in config: {len(rule_names)}  ({len(trend_rules)} trend + {len(carry_rules)} carry-family)")

# ============================================================
# Per-rule aggregated P&L: sum over instruments, weighted
# ============================================================
print("\nComputing per-rule aggregated P&L...")
rule_pnl = {}  # rule_name -> daily P&L series (portfolio-level, $)
for r in rule_names:
    per_inst_pnls = []
    for inst in instruments:
        try:
            p = system.accounts.pandl_for_instrument_forecast(inst, r)
            ts = p.as_ts  # % returns as series
            w = instrument_weights.get(inst, 0)
            # Weight the rule's P&L by instrument_weight (the config weight)
            per_inst_pnls.append(ts * w)
        except Exception:
            pass
    if per_inst_pnls:
        rule_pnl[r] = pd.concat(per_inst_pnls, axis=1).sum(axis=1)

# Align and restrict to backtest window
rule_df = pd.concat(rule_pnl, axis=1).dropna(how="all").fillna(0)
rule_df = rule_df[rule_df.index >= "2016-01-01"]
print(f"  {rule_df.shape[0]} days x {rule_df.shape[1]} rules")

# ============================================================
# Per-rule stats table
# ============================================================
print("\n" + "=" * 95)
print("Per-rule 10-year stats (portfolio-level, weighted across instruments)")
print("=" * 95)
print(f"{'Rule':>15s}  {'Family':>10s}  {'Ann mean':>10s}  {'Ann std':>10s}  "
      f"{'Sharpe':>7s}  {'Median':>8s}  {'Skew':>7s}  {'Min':>8s}  {'Max':>8s}")

def classify(r):
    if r.startswith("ewmac"): return "ewmac"
    if r.startswith("accel"): return "accel"
    if r.startswith("breakout"): return "breakout"
    if r.startswith("carry_accel"): return "carry_accel"
    if r.startswith("relcarry"): return "relcarry"
    if r.startswith("carry"): return "carry"
    return "?"

stats_rows = []
for r in rule_names:
    if r not in rule_df.columns:
        continue
    s = rule_df[r].dropna()
    ann_mean = s.mean() * 252
    ann_std = s.std() * np.sqrt(252)
    sharpe = ann_mean / ann_std if ann_std > 0 else float("nan")
    median_daily = s.median()
    skew_val = float(scipy_skew(s.values)) if len(s) > 3 else 0.0
    fam = classify(r)
    stats_rows.append((r, fam, ann_mean, ann_std, sharpe, median_daily, skew_val, s.min(), s.max()))
    print(f"{r:>15s}  {fam:>10s}  {ann_mean:>+10.1f}  {ann_std:>10.1f}  "
          f"{sharpe:>+7.3f}  {median_daily:>+8.3f}  {skew_val:>+7.2f}  "
          f"{s.min():>+8.1f}  {s.max():>+8.1f}")

# ============================================================
# Correlation matrices within family
# ============================================================
def print_corr(df_subset, title):
    print(f"\n{title}")
    corr = df_subset.corr()
    print(f"{'':>15s}", end="")
    for c in corr.columns:
        print(f"{c:>12s}", end="")
    print()
    for idx in corr.index:
        print(f"{idx:>15s}", end="")
        for c in corr.columns:
            v = corr.loc[idx, c]
            print(f"{v:>+12.3f}", end="")
        print()

print("\n" + "=" * 95)
print("Correlation matrices — within family")
print("=" * 95)

trend_cols = [r for r in trend_rules if r in rule_df.columns]
print_corr(rule_df[trend_cols], "TREND family (ewmac + accel + breakout)")

carry_cols = [r for r in carry_rules if r in rule_df.columns]
print_corr(rule_df[carry_cols], "\nCARRY family (carry + relcarry + carry_accel)")

# ============================================================
# Cross-family correlation (trend vs carry)
# ============================================================
print("\n" + "=" * 95)
print("Cross-family summary correlations")
print("=" * 95)

# Aggregate each family to one series
trend_agg = rule_df[trend_cols].mean(axis=1)
carry_agg = rule_df[carry_cols].mean(axis=1)

print(f"\nAggregate TREND vs CARRY correlation: {trend_agg.corr(carry_agg):+.3f}")

# Sub-family aggregates
ewmac_cols = [r for r in rule_df.columns if r.startswith("ewmac")]
accel_cols = [r for r in rule_df.columns if r.startswith("accel")]
breakout_cols = [r for r in rule_df.columns if r.startswith("breakout")]
carry_plain_cols = [r for r in rule_df.columns if r.startswith("carry") and not r.startswith("carry_accel")]
relcarry_cols = [r for r in rule_df.columns if r.startswith("relcarry")]
carry_accel_cols = [r for r in rule_df.columns if r.startswith("carry_accel")]

sub_families = {
    "ewmac":       rule_df[ewmac_cols].mean(axis=1),
    "accel":       rule_df[accel_cols].mean(axis=1),
    "breakout":    rule_df[breakout_cols].mean(axis=1),
    "carry":       rule_df[carry_plain_cols].mean(axis=1),
    "relcarry":    rule_df[relcarry_cols].mean(axis=1),
    "carry_accel": rule_df[carry_accel_cols].mean(axis=1),
}

print("\nSub-family correlation matrix:")
subfam_df = pd.DataFrame(sub_families)
subfam_corr = subfam_df.corr()
print(f"{'':>14s}", end="")
for c in subfam_corr.columns:
    print(f"{c:>14s}", end="")
print()
for idx in subfam_corr.index:
    print(f"{idx:>14s}", end="")
    for c in subfam_corr.columns:
        print(f"{subfam_corr.loc[idx, c]:>+14.3f}", end="")
    print()
