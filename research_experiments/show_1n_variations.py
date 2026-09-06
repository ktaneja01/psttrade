"""Compare three weight schemes:
1. True 1/N (equal cash)
2. Inverse-vol (equal risk per instrument, ignoring correlations)
3. Risk parity with shrunk correlations (equal risk contribution via covariance)
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize

asset_classes = {
    "Bonds":            ["US10", "US10U", "US20", "US30", "BUND", "GILT"],
    "Grains":           ["REDWHEAT", "SOYMEAL", "SOYOIL", "WHEAT", "CORN", "SOYBEAN"],
    "Energy-Livestock": ["CRUDE_W", "GAS_US", "GASOILINE", "HEATOIL", "GAS-LAST",
                         "LIVECOW", "FEEDCOW", "LEANHOG", "RICE", "GBPJPY",
                         "COFFEE", "OJ", "GASOIL"],
    "Equity-Risk":      ["SP500", "NASDAQ", "RUSSELL", "DOW", "NIKKEI", "SP400",
                         "CAC", "DAX", "EUROSTX", "FTSE100", "VIX", "V2X"],
    "G10-FX":           ["EUR", "JPY", "GBP", "AUD", "NZD", "CHF", "PLN", "EURCAD"],
    "EM-Metal-Crypto":  ["MXP", "ZAR", "BRE", "GOLD", "SILVER", "COPPER", "PLAT", "PALLAD",
                         "BITCOIN", "ETHEREUM"],
}
instruments = [i for insts in asset_classes.values() for i in insts]
instrument_to_class = {i: c for c, insts in asset_classes.items() for i in insts}
N = len(instruments)

# Load returns
def daily_returns(code):
    s = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{code}.parquet").squeeze()
    s = s.dropna().resample("1B").last().ffill()
    s = s[s > 0]
    return s.pct_change().dropna().rename(code)

returns_df = pd.concat([daily_returns(i) for i in instruments], axis=1)
returns_df = returns_df[returns_df.index >= "2016-01-01"].dropna(thresh=int(N * 0.5)).fillna(0)
weekly = returns_df.resample("W").sum()

# Vols
vols = {i: float(weekly[i].std() * np.sqrt(52)) for i in instruments}
corr = weekly.corr()

# Shrunk correlations (50% toward average)
avg_corr = corr.values[~np.eye(N, dtype=bool)].mean()
shrunk_corr_vals = 0.5 * corr.values + 0.5 * avg_corr
np.fill_diagonal(shrunk_corr_vals, 1.0)
shrunk_corr = pd.DataFrame(shrunk_corr_vals, index=corr.index, columns=corr.columns)

# Shrunk covariance
stdev_array = np.array([vols[i] for i in instruments])
shrunk_cov = np.outer(stdev_array, stdev_array) * shrunk_corr_vals

# ============================================================
# Method 1: True 1/N equal cash
# ============================================================
w_1n = {inst: 1.0 / N for inst in instruments}

# ============================================================
# Method 2: Inverse-vol (ignores correlations)
# ============================================================
inv_vols = {inst: 1.0 / vols[inst] for inst in instruments}
sum_inv = sum(inv_vols.values())
w_invvol = {inst: v / sum_inv for inst, v in inv_vols.items()}

# ============================================================
# Method 3: Risk Parity with shrunk correlations
# ============================================================
def risk_parity_objective(w, cov):
    portfolio_vol = np.sqrt(w @ cov @ w)
    marginal_risk = (cov @ w) / portfolio_vol
    risk_contributions = w * marginal_risk
    # Want each risk_contribution equal
    target = portfolio_vol / N
    return np.sum((risk_contributions - target) ** 2)

x0 = np.ones(N) / N
constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
bounds = [(0.001, 1.0)] * N
result = minimize(risk_parity_objective, x0, args=(shrunk_cov,),
                  method="SLSQP", bounds=bounds, constraints=constraints,
                  options={"maxiter": 500, "ftol": 1e-10})
w_rp_shrunk = {inst: result.x[idx] for idx, inst in enumerate(instruments)}

# ============================================================
# Display
# ============================================================
print("=" * 95)
print("WEIGHT COMPARISON — 1/N vs inverse-vol vs risk-parity-with-shrunk-correlations")
print("=" * 95)

print(f"\nShrunk correlation avg: {avg_corr:.3f} (pulled 50% toward this)")
print()
print(f"{'Cluster':>18s}  {'1/N':>7s}  {'inv-vol':>9s}  {'RP+shrunk':>11s}")
for cls, members in asset_classes.items():
    w1 = sum(w_1n[m] for m in members) * 100
    wi = sum(w_invvol[m] for m in members) * 100
    wr = sum(w_rp_shrunk[m] for m in members) * 100
    print(f"{cls:>18s}  {w1:>+6.2f}%  {wi:>+8.2f}%  {wr:>+10.2f}%")

# Per-instrument detailed
print()
for cls, members in asset_classes.items():
    print(f"\n{cls}:")
    print(f"{'':>16s} {'1/N':>8s} {'inv-vol':>10s} {'RP+shrunk':>11s}")
    for inst in sorted(members, key=lambda x: -w_rp_shrunk.get(x, 0)):
        v = vols[inst] * 100
        print(f"  {inst:<14s}  {w_1n[inst]*100:>6.2f}%  {w_invvol[inst]*100:>+8.2f}%  {w_rp_shrunk[inst]*100:>+10.2f}%  (vol={v:5.1f}%)")

# Dispersion
print("\n" + "=" * 95)
print("DISPERSION STATS")
print("=" * 95)
for name, w in [("1/N", w_1n), ("inv-vol", w_invvol), ("RP+shrunk", w_rp_shrunk)]:
    vals = [v*100 for v in w.values()]
    print(f"  {name:<12s}  max={max(vals):>5.2f}%  min={min(vals):>5.3f}%  "
          f"median={np.median(vals):>5.2f}%  stdev={np.std(vals):>5.2f}%  "
          f"zeros={sum(1 for v in vals if v < 0.1)}")
