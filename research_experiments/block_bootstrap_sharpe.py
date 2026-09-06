"""Block bootstrap confidence interval on Sharpe ratio.

Non-overlapping 126-day (6-month) blocks, sampled with replacement to
preserve serial correlation and regime clustering. 2000 resamples.
Reports distribution, 95% CI, and whether 0 / 0.30 / 0.45 are inside it.
"""
import os
os.environ["CAPITAL"] = "500000"

import numpy as np
import pandas as pd

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

r = pd.Series(system.accounts.portfolio().percent).astype(float) / 100.0
r = r.dropna().values
T = len(r)
observed_sharpe = float(r.mean() / r.std() * np.sqrt(252))
print(f"Daily returns: T={T}, observed annualized Sharpe = {observed_sharpe:+.3f}")

BLOCK_LEN = 126   # 6 months
N_BOOTS = 2000
RNG = np.random.default_rng(42)


def block_bootstrap_sharpe(r, block_len, n_boots):
    n_blocks_needed = int(np.ceil(len(r) / block_len))
    n_source_blocks = len(r) - block_len + 1
    sharpes = np.empty(n_boots)
    for i in range(n_boots):
        starts = RNG.integers(0, n_source_blocks, size=n_blocks_needed)
        pieces = [r[s:s + block_len] for s in starts]
        sample = np.concatenate(pieces)[:len(r)]
        sd = sample.std()
        sharpes[i] = sample.mean() / sd * np.sqrt(252) if sd > 0 else 0.0
    return sharpes


print(f"\nRunning {N_BOOTS} block-bootstrap resamples (block_len={BLOCK_LEN} days)...")
boot_sr = block_bootstrap_sharpe(r, BLOCK_LEN, N_BOOTS)

pcts = np.percentile(boot_sr, [2.5, 10, 25, 50, 75, 90, 97.5])

print("\n" + "=" * 60)
print("Block-bootstrap Sharpe distribution")
print("=" * 60)
print(f"  Observed (point estimate): {observed_sharpe:+.3f}")
print(f"  Bootstrap mean:            {boot_sr.mean():+.3f}")
print(f"  Bootstrap SD:              {boot_sr.std():.3f}")
print(f"\n  Percentiles:")
for p, v in zip([2.5, 10, 25, 50, 75, 90, 97.5], pcts):
    marker = "  ← 95% CI low" if p == 2.5 else ("  ← median" if p == 50 else ("  ← 95% CI high" if p == 97.5 else ""))
    print(f"    {p:>5.1f}%: {v:>+7.3f}{marker}")

# Threshold tests
print(f"\n  P(Sharpe > 0):    {(boot_sr > 0).mean():.3f}")
print(f"  P(Sharpe > 0.20): {(boot_sr > 0.20).mean():.3f}")
print(f"  P(Sharpe > 0.30): {(boot_sr > 0.30).mean():.3f}")
print(f"  P(Sharpe > 0.45): {(boot_sr > 0.45).mean():.3f}")

ci_low, ci_high = pcts[0], pcts[-1]
print(f"\n  95% CI: [{ci_low:+.3f}, {ci_high:+.3f}]  (width = {ci_high - ci_low:.3f})")
print(f"  Zero inside CI: {'YES (noisy)' if ci_low < 0 < ci_high else 'NO (consistent sign)'}")

# Save histogram
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(11, 5.5))
ax.hist(boot_sr, bins=60, color="#4a90e2", edgecolor="white")
for v, lbl, c in [
    (observed_sharpe, f"Observed {observed_sharpe:+.2f}", "red"),
    (boot_sr.mean(),   f"Mean {boot_sr.mean():+.2f}",      "black"),
    (0.0,              "0",                                 "gray"),
    (ci_low,           f"2.5% {ci_low:+.2f}",               "orange"),
    (ci_high,          f"97.5% {ci_high:+.2f}",             "orange"),
]:
    ax.axvline(v, color=c, linestyle="--", linewidth=1.4, label=lbl)
ax.legend(loc="upper left", fontsize=9)
ax.set_xlabel("Annualized Sharpe")
ax.set_ylabel("Count")
ax.set_title(f"Block-bootstrap Sharpe distribution "
             f"(T={T} days, block={BLOCK_LEN}d, {N_BOOTS} resamples)\n"
             f"Point estimate {observed_sharpe:+.3f}, "
             f"95% CI [{ci_low:+.3f}, {ci_high:+.3f}]")
plt.tight_layout()
plt.savefig("/tmp/bootstrap_sharpe_hist.png", dpi=120)
print(f"\nHistogram saved to /tmp/bootstrap_sharpe_hist.png")
