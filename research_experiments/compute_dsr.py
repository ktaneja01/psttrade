"""Deflated Sharpe Ratio — Bailey & Lopez de Prado (2014) "The Deflated Sharpe Ratio".

Corrects observed Sharpe for the multiple-testing bias induced by trialing N
strategies and reporting the best. Returns the probability that the true
Sharpe exceeds the benchmark (SR*, the expected max of N trials).

Reads the final portfolio returns series from the last backtest output
(/tmp/signals_sys_only_vt25_accel8.txt is the winning config at +0.45 SR).
"""
import os
os.environ["CAPITAL"] = "500000"

import numpy as np
import pandas as pd
from scipy.stats import norm, skew as scipy_skew, kurtosis as scipy_kurt

# ============================================================
# Inputs — the Sharpe values we tested in this session
# ============================================================
# Each entry = observed annualized Sharpe from a distinct backtest config.
# This is the selection universe; DSR penalizes the best against this set.
TESTED_SHARPES = [
    0.35,  # estimated weights 500K
    0.26,  # frozen 200K
    0.41,  # frozen 400K
    0.39,  # frozen 500K
    0.33,  # frozen 600K
    0.24,  # frozen 800K
    0.31,  # frozen 1M
    0.34,  # frozen 5M
    0.35,  # frozen 500K vt25
    0.48,  # spot_ewmac only, 50/50, 500K
    0.47,  # all-spot-trend, 50/50, 500K vt20
    0.39,  # sys-only (no SP500/GOLD), 500K vt20
    0.36,  # sys-only 500K vt25
    0.45,  # sys-only 500K vt25 + accel8  (← current best, the one we test)
]
OBSERVED_SR = 0.45
N_TRIALS = len(TESTED_SHARPES)

# ============================================================
# Need the actual daily return series of the winning config to compute
# higher-moment corrections (skew, kurtosis, T).
# Reconstruct from the signals.py system — fastest path.
# ============================================================
print("Rebuilding system to extract daily portfolio returns...")
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

returns = pd.Series(system.accounts.portfolio().percent).astype(float) / 100.0
returns = returns.dropna()
T = len(returns)
sk = float(scipy_skew(returns))
ex_kurt = float(scipy_kurt(returns, fisher=True))  # excess kurtosis (normal = 0)

print(f"\nDaily return series: T={T} obs, skew={sk:+.3f}, excess_kurt={ex_kurt:+.3f}")

# ============================================================
# Bailey & Lopez de Prado DSR formula
# ============================================================
# Non-annualized daily Sharpe (Bailey/Prado work per-period)
sr_daily_obs = OBSERVED_SR / np.sqrt(252)
sharpes_daily = np.array(TESTED_SHARPES) / np.sqrt(252)

# Variance of Sharpes across trials (empirical)
var_sr_trials = float(np.var(sharpes_daily, ddof=1))
sd_sr_trials = float(np.sqrt(var_sr_trials))

# Expected max of N independent Gaussian trials
euler_gamma = 0.5772156649
sr_star_daily = sd_sr_trials * (
    (1 - euler_gamma) * norm.ppf(1 - 1.0 / N_TRIALS)
    + euler_gamma * norm.ppf(1 - 1.0 / (N_TRIALS * np.e))
)

sr_star_annual = sr_star_daily * np.sqrt(252)

# Probabilistic Sharpe with higher-moment correction
num = (sr_daily_obs - sr_star_daily) * np.sqrt(T - 1)
denom = np.sqrt(1 - sk * sr_daily_obs + (ex_kurt) / 4 * sr_daily_obs**2)
# Note: paper uses (γ4 - 1); scipy returns excess kurtosis (γ4 - 3), so use "ex_kurt + 2" in its place
denom_paper = np.sqrt(1 - sk * sr_daily_obs + (ex_kurt + 2) / 4 * sr_daily_obs**2)

z = num / denom_paper
dsr = norm.cdf(z)

# Also compute plain PSR against SR=0 (no multiple-testing penalty) for comparison
z0 = sr_daily_obs * np.sqrt(T - 1) / denom_paper
psr0 = norm.cdf(z0)

# ============================================================
# Report
# ============================================================
print("\n" + "=" * 70)
print("Deflated Sharpe Ratio — Bailey & Lopez de Prado (2014)")
print("=" * 70)
print(f"  Observed SR (annualized):          {OBSERVED_SR:+.3f}")
print(f"  Number of trials (configs tested): {N_TRIALS}")
print(f"  Trial universe SD of SR:           {sd_sr_trials * np.sqrt(252):.3f} (annual)")
print(f"  Expected max SR under null SR*:    {sr_star_annual:+.3f} (annual)")
print(f"  Skew of daily returns:             {sk:+.3f}")
print(f"  Excess kurtosis of daily returns:  {ex_kurt:+.3f}")
print(f"  T (observations):                  {T}")
print()
print(f"  PSR (vs SR=0, no multiple-test):   {psr0:.3f}  ← prob true SR > 0")
print(f"  DSR (vs SR* = {sr_star_annual:+.2f}):             {dsr:.3f}  ← prob true SR > SR*")
print()
print("Interpretation:")
if dsr >= 0.95:
    verdict = "STRONG — true SR plausibly exceeds the multiple-test threshold."
elif dsr >= 0.80:
    verdict = "MODERATE — some evidence, but not at the 95% confidence bar."
elif dsr >= 0.50:
    verdict = "WEAK — observed Sharpe barely distinguishable from best-of-N noise."
else:
    verdict = "NONE — strategy is statistically indistinguishable from selection bias."
print(f"  {verdict}")

# ============================================================
# Sensitivity analysis — what if we tested more/fewer configs?
# ============================================================
print("\n" + "=" * 70)
print("Sensitivity: DSR as function of N_TRIALS (how many configs we searched)")
print("=" * 70)
print(f"{'N trials':>10} {'SR*':>10} {'DSR':>10}  {'Verdict':>40}")
for n in [3, 5, 10, 14, 25, 50, 100]:
    sr_star_n = sd_sr_trials * (
        (1 - euler_gamma) * norm.ppf(1 - 1.0 / n)
        + euler_gamma * norm.ppf(1 - 1.0 / (n * np.e))
    )
    z_n = (sr_daily_obs - sr_star_n) * np.sqrt(T - 1) / denom_paper
    dsr_n = norm.cdf(z_n)
    v = ("STRONG" if dsr_n >= 0.95 else
         "MODERATE" if dsr_n >= 0.80 else
         "WEAK" if dsr_n >= 0.50 else "NONE")
    print(f"{n:>10} {sr_star_n * np.sqrt(252):>+10.3f} {dsr_n:>10.3f}  {v:>40}")
