"""Turnover and per-trade cost of accel8 across instruments."""
from signals import system, instruments
import numpy as np

print("=" * 75)
print("accel8: turnover and annualized cost by instrument")
print("=" * 75)
print(f"{'Instrument':>14s}  {'Turnover/yr':>12s}  {'Per-trade SR':>13s}  {'Annual SR cost':>15s}")

turnovers, costs = [], []
for inst in instruments:
    try:
        t = system.accounts.forecast_turnover(inst, "accel8")
        # Annualized cost per-instrument-per-rule (= per-trade × turnover)
        ann_cost = system.accounts.get_SR_cost_for_instrument_forecast(inst, "accel8")
        per_trade = ann_cost / t if t > 0 else 0
        turnovers.append(t)
        costs.append(ann_cost)
        print(f"{inst:>14s}  {t:>12.1f}  {per_trade:>13.5f}  {ann_cost:>+15.4f}")
    except Exception as e:
        print(f"{inst:>14s}  ERROR: {e}")

print(f"\n{'AVERAGE':>14s}  {np.mean(turnovers):>12.1f}  "
      f"{np.mean([c/t for c, t in zip(costs, turnovers) if t > 0]):>13.5f}  "
      f"{np.mean(costs):>+15.4f}")
print(f"{'MEDIAN':>14s}  {np.median(turnovers):>12.1f}")
print(f"{'MAX':>14s}  {np.max(turnovers):>12.1f}")
print(f"\nCompare rule-level cost ceiling: 0.10 annualized SR cost")
print(f"Number of instruments where accel8 exceeds ceiling: "
      f"{sum(1 for c in costs if c > 0.10)} / {len(costs)}")
