"""Standalone VIX strategy — Concretum eVRP+BoC with continuous vol-of-vol sizing.

Regime gating (from paper Strategy 3/4):
  If  eVRP > 0  and VIX < VIX3M:   SHORT VIX, target_vol = clip(VIX/100, MAX)
  Elif eVRP <= 0 and VIX < VIX3M:  SHORT VIX, target_vol = 0.5 × clip(VIX/100, MAX)
  Elif eVRP <= 0 and VIX > VIX3M:  LONG VIX,  target_vol = clip(VIX/100, MAX)
  Else:                            FLAT

Continuous sizing layer:
  - Target portfolio vol scales linearly with VIX level (paper intent: bigger
    risk allocation in elevated-vol regimes where premium is rich).
  - Number of contracts derived via vol-of-vol target (rolling std of daily
    ΔVIX), so realized $-vol exposure is honest. As VIX rises, vol-of-vol
    rises too, so contract count typically falls — but $-vol exposure
    grows, matching the economic intent.
  - Cap on target_vol prevents 80%+ exposure during 2020-style spikes.

Where:
  eRV30 = std(last 10 daily SPY returns) × sqrt(252) × 100      [annualized vol %]
  eVRP  = VIX − eRV30                                            [vol points]
  size = VIX/100 × capital, expressed as $-notional in VIX futures

Approximations from the paper:
  - VIX_t        ≈ F1 (CARRY column, multiple_prices)            [converges to spot at expiry]
  - VIX3M_t      = linear interp of F2/F3 to 93-day maturity
  - SPY proxy    = SP500 futures back-adjusted (daily close)
  - Trading veh. = VIX futures directly (paper trades ETN proxies; same $-notional sizing)

Run:    CAPITAL=250000 pst-env/bin/python vix_contango_strategy.py
Output: stats to stdout, daily P&L → /tmp/vix_contango_pnl.csv
"""
import os
import numpy as np
import pandas as pd
from scipy.stats import skew as scipy_skew, kurtosis as scipy_kurt
from scipy.optimize import minimize

# =====================================================================
# Config
# =====================================================================
CAPITAL = int(os.environ.get("CAPITAL", 250_000))
TARGET_VOL_DIVISOR = 100.0   # paper VIX/100 base → target_vol grows linearly with VIX
MAX_TARGET_VOL = 0.25        # cap portfolio vol target at 25%
HALF_FACTOR = 0.5            # short_half regime gets half the target vol
VOL_OF_VOL_EWMA_SPAN = 35    # EWMA span for daily ΔVIX std (longer = stress-memory)
REBAL_THRESHOLD_PCT = 0.02   # 2% of capital — don't trade for smaller drifts

# eRV30 via GARCH(1,1), walk-forward fit
GARCH_FIT_WINDOW = 504       # fit on past 2 years
GARCH_REFIT_EVERY = 22       # refit monthly
GARCH_MIN_FIT = 126          # need 6mo min before first fit
OOS_START = "2024-01-01"

# VIX contract specifics
VIX_MULTIPLIER = 1000.0                  # $1,000 per VIX point
VIX_PERBLOCK_COMMISSION = 2.5942         # USD/contract (already GST-loaded)
VIX_SPREAD_PTS = 0.025                   # half-spread in vol points

MP_PATH = "/usr/local/bc_data/futures_multiple_prices/VIX.parquet"
ADJ_PATH = "/usr/local/bc_data/futures_adjusted_prices/VIX.parquet"
SP500_PATH = "/usr/local/bc_data/futures_adjusted_prices/SP500.parquet"
VIX_SPOT_PATH = "/usr/local/bc_data/vol_indices/VIX_spot.parquet"   # CBOE ^VIX history


# =====================================================================
# Synthetic VIX3M
# =====================================================================
def _contract_mid_month(contract_code) -> pd.Timestamp:
    c = int(contract_code)
    yr, mo = c // 10000, (c // 100) % 100
    return pd.Timestamp(year=yr, month=mo, day=15)


def synthetic_vix3m(mp: pd.DataFrame) -> pd.Series:
    mid_f2 = mp["PRICE_CONTRACT"].apply(_contract_mid_month)
    mid_f3 = mp["FORWARD_CONTRACT"].apply(_contract_mid_month)
    f2_days = (mid_f2 - mp.index).dt.days.astype(float)
    f3_days = (mid_f3 - mp.index).dt.days.astype(float)
    weight = ((93.0 - f2_days) / (f3_days - f2_days)).clip(0.0, 2.0)
    return mp["PRICE"] + (mp["FORWARD"] - mp["PRICE"]) * weight


def synthetic_spot_vix(mp: pd.DataFrame) -> pd.Series:
    """
    Linear extrapolation of F1 → F2 slope back to today (days = 0).
    Removes the structural F1-above-spot bias (~1-2 vol points in contango).

      slope_per_day = (F2 − F1) / (d2 − d1)
      spot_synth    = F1 − d1 × slope_per_day

    Self-corrects across regimes:
      contango      → spot < F1
      backwardation → spot > F1 (slope is negative)
      near-expiry   → spot ≈ F1
    """
    mid_f1 = mp["CARRY_CONTRACT"].apply(_contract_mid_month)
    mid_f2 = mp["PRICE_CONTRACT"].apply(_contract_mid_month)
    d1 = (mid_f1 - mp.index).dt.days.astype(float)
    d2 = (mid_f2 - mp.index).dt.days.astype(float)
    safe_diff = (d2 - d1).replace(0, np.nan)
    slope_per_day = (mp["PRICE"] - mp["CARRY"]) / safe_diff
    return mp["CARRY"] - d1 * slope_per_day


# =====================================================================
# GARCH(1,1) maximum-likelihood estimation
# σ²_t = ω + α·r²_{t-1} + β·σ²_{t-1},  with α + β < 1 for stationarity.
# Long-run variance: ω / (1 − α − β).
# =====================================================================
def _garch_neg_loglik(params: np.ndarray, returns: np.ndarray) -> float:
    omega, alpha, beta = params
    if omega <= 1e-12 or alpha < 0 or beta < 0 or alpha + beta >= 0.9999:
        return 1e10
    n = len(returns)
    sigma2 = np.empty(n)
    sigma2[0] = max(np.var(returns), 1e-10)
    for t in range(1, n):
        sigma2[t] = omega + alpha * returns[t - 1] ** 2 + beta * sigma2[t - 1]
        if sigma2[t] <= 0:
            return 1e10
    return 0.5 * np.sum(np.log(sigma2) + returns ** 2 / sigma2)


def _fit_garch(returns: np.ndarray) -> np.ndarray:
    """Fit GARCH(1,1) via SLSQP. Returns (omega, alpha, beta)."""
    r = returns - np.mean(returns)
    target_var = max(np.var(r), 1e-10)
    x0 = np.array([target_var * 0.05, 0.05, 0.90])
    bounds = [(1e-12, target_var * 10), (0.0, 1.0), (0.0, 1.0)]
    constraints = {"type": "ineq", "fun": lambda x: 0.9999 - x[1] - x[2]}
    res = minimize(
        _garch_neg_loglik, x0, args=(r,), method="SLSQP",
        bounds=bounds, constraints=constraints,
        options={"maxiter": 200, "ftol": 1e-7},
    )
    if not res.success or np.any(np.isnan(res.x)):
        return np.array([target_var * 0.05, 0.05, 0.90])  # fallback to plausible defaults
    return res.x


def garch_walkforward_vol(returns: pd.Series,
                          fit_window: int = GARCH_FIT_WINDOW,
                          refit_every: int = GARCH_REFIT_EVERY,
                          min_fit: int = GARCH_MIN_FIT) -> pd.Series:
    """
    Walk-forward GARCH(1,1) one-step-ahead conditional vol forecast.
    Refits parameters every `refit_every` days using past `fit_window` days.
    Returns annualized vol forecast (in %) at each time t.
    """
    r_arr = (returns - returns.mean()).fillna(0.0).values
    n = len(r_arr)
    sigma2 = np.full(n, np.nan)
    sigma2[0] = np.nanvar(r_arr[:min_fit])

    last_params = None
    next_refit = min_fit
    for t in range(1, n):
        if t >= next_refit:
            start = max(0, t - fit_window)
            try:
                last_params = _fit_garch(r_arr[start:t])
            except Exception:
                pass
            next_refit = t + refit_every

        if last_params is not None:
            omega, alpha, beta = last_params
            prev_var = sigma2[t - 1] if not np.isnan(sigma2[t - 1]) else omega / max(1.0 - alpha - beta, 1e-6)
            sigma2[t] = omega + alpha * r_arr[t - 1] ** 2 + beta * prev_var
        else:
            sigma2[t] = sigma2[t - 1] if not np.isnan(sigma2[t - 1]) else np.nanvar(r_arr[:max(t, 1)])

    sigma_daily = np.sqrt(np.clip(sigma2, 1e-10, None))
    return pd.Series(sigma_daily * np.sqrt(252) * 100, index=returns.index)


# =====================================================================
# eVRP: expected Volatility Risk Premium (GARCH-based)
# =====================================================================
def compute_eVRP(spy_close: pd.Series, vix_spot: pd.Series) -> pd.Series:
    """
    eRV30_t = GARCH(1,1) conditional vol forecast × sqrt(252) × 100  (annualized %)
    eVRP_t  = VIX_t − eRV30_t
    """
    spy_rets = spy_close.pct_change()
    eRV30 = garch_walkforward_vol(spy_rets)
    aligned_vix, aligned_eRV = vix_spot.align(eRV30, join="inner")
    return aligned_vix - aligned_eRV, aligned_eRV


# =====================================================================
# Position sizing — Strategy 4
# =====================================================================
def regime_and_target_vol(vix: pd.Series, vix3m: pd.Series, eVRP: pd.Series) -> pd.DataFrame:
    """
    Returns DataFrame with:
      direction:  +1 long VIX, -1 short VIX, 0 flat
      target_vol: target ANNUAL portfolio vol fraction (continuous in VIX level)
      regime:     string label

    Continuous sizing: base_target = clip(VIX/100, 0, MAX_TARGET_VOL).
    short_full and long_full → base_target.
    short_half → 0.5 × base_target.
    """
    df = pd.DataFrame(index=vix.index)
    df["vix"] = vix
    df["vix3m"] = vix3m
    df["eVRP"] = eVRP

    contango = vix < vix3m
    backward = vix > vix3m

    short_full = (eVRP > 0) & contango           # best: rich premium + contango
    short_half = (eVRP <= 0) & contango          # weak premium but still contango
    long_full = (eVRP <= 0) & backward           # backwardation + premium gone

    base_target = np.clip(vix / TARGET_VOL_DIVISOR, 0.0, MAX_TARGET_VOL)

    df["direction"] = 0
    df["target_vol"] = 0.0
    df["regime"] = "flat"

    df.loc[short_full, "direction"] = -1
    df.loc[short_full, "target_vol"] = base_target[short_full]
    df.loc[short_full, "regime"] = "short_full"

    df.loc[short_half, "direction"] = -1
    df.loc[short_half, "target_vol"] = HALF_FACTOR * base_target[short_half]
    df.loc[short_half, "regime"] = "short_half"

    df.loc[long_full, "direction"] = +1
    df.loc[long_full, "target_vol"] = base_target[long_full]
    df.loc[long_full, "regime"] = "long_full"

    return df


def vol_of_vol_per_contract(adj_price: pd.Series, ewma_span: int = VOL_OF_VOL_EWMA_SPAN) -> pd.Series:
    """
    Annualized $-volatility of one VIX futures contract.

      vol_of_vol = EWMA std of daily ΔVIX (span=10) [vol-points/day]
      ann_$_vol  = vol_of_vol × √252 × $1,000        [USD/year per contract]

    EWMA span=10 is faster-reacting than 35d rolling — cuts contracts sooner
    when vol-of-vol jumps during run-up to a spike.

    Uses back-adjusted VIX so vol estimate isn't polluted by roll discontinuities.
    """
    daily_change = adj_price.diff()
    daily_std_pts = daily_change.ewm(span=ewma_span, min_periods=5).std()
    return daily_std_pts * np.sqrt(252) * VIX_MULTIPLIER


# =====================================================================
# Rebalance threshold — 2% of capital
# =====================================================================
def apply_rebalance_threshold(target_contracts: pd.Series, vix_price: pd.Series,
                              capital: float, threshold_pct: float = 0.02) -> pd.Series:
    """
    Don't update held position unless the |Δnotional| would exceed threshold% of capital.
    """
    threshold_dol = capital * threshold_pct
    held_vals = []
    last = 0.0
    for t, p in zip(target_contracts.values, vix_price.values):
        if pd.isna(t) or pd.isna(p):
            held_vals.append(last)
            continue
        delta_notional = abs(t - last) * p * VIX_MULTIPLIER
        if delta_notional > threshold_dol:
            last = t
        held_vals.append(last)
    return pd.Series(held_vals, index=target_contracts.index)


# =====================================================================
# Stats helpers
# =====================================================================
def _stats_block(pnl: pd.Series, capital: float, label: str) -> dict:
    pct = pnl / capital
    if len(pct) < 20 or pct.std() == 0:
        return {"label": label, "n": len(pct)}
    ann_mean = pct.mean() * 252
    ann_std = pct.std() * np.sqrt(252)
    sharpe = ann_mean / ann_std if ann_std > 0 else 0
    ds = pct[pct < 0].std() * np.sqrt(252)
    sortino = ann_mean / ds if ds > 0 else 0
    cum = pnl.cumsum()
    dd = cum - cum.cummax()
    return {
        "label": label, "n": len(pct),
        "sharpe": sharpe, "sortino": sortino,
        "ann_mean_pct": ann_mean * 100, "ann_std_pct": ann_std * 100,
        "ann_mean_dollar": ann_mean * capital,
        "max_dd_dollar": dd.min(), "max_dd_pct": dd.min() / capital * 100,
        "skew": scipy_skew(pct.dropna()), "kurt": scipy_kurt(pct.dropna()),
        "hit_rate": (pct > 0).mean() * 100,
        "worst_day": pct.min() * 100, "best_day": pct.max() * 100,
    }


def _print_stats(s: dict):
    if s.get("n", 0) < 20:
        print(f"  {s['label']:<18} insufficient data (n={s.get('n',0)})")
        return
    print(f"  {s['label']:<18} "
          f"SR={s['sharpe']:+.3f}  Sortino={s['sortino']:+.3f}  "
          f"AnnRet={s['ann_mean_pct']:+6.2f}%  AnnVol={s['ann_std_pct']:5.2f}%  "
          f"AnnP&L=${s['ann_mean_dollar']:>+10,.0f}  "
          f"MaxDD=${s['max_dd_dollar']:>+10,.0f} ({s['max_dd_pct']:+5.1f}%)  "
          f"Hit={s['hit_rate']:.1f}%  Skew={s['skew']:+.2f}")


# =====================================================================
# Main
# =====================================================================
def main():
    print(f"Concretum eVRP+BoC with vol-of-vol sizing — CAPITAL=${CAPITAL:,}, "
          f"target_vol = clip(VIX/{TARGET_VOL_DIVISOR:.0f}, 0, {MAX_TARGET_VOL*100:.0f}%), "
          f"vol-of-vol EWMA span = {VOL_OF_VOL_EWMA_SPAN}d")
    print("=" * 110)

    # -------- 1. Load multiple_prices, compute term structure --------
    print("\n[1/5] Loading VIX term structure...")
    mp = (
        pd.read_parquet(MP_PATH).resample("1B").last().ffill()
        .dropna(subset=["CARRY", "PRICE", "FORWARD"])
    )
    # Real CBOE spot VIX from /usr/local/bc_data/vol_indices/VIX_spot.parquet
    spot_raw = pd.read_parquet(VIX_SPOT_PATH).squeeze()
    spot_raw.index = pd.DatetimeIndex(spot_raw.index).normalize()
    front = spot_raw.reindex(mp.index.normalize()).ffill()    # actual ^VIX
    front.index = mp.index                                     # restore intraday timestamps
    vix3m = synthetic_vix3m(mp)         # interp F2/F3 → 93d
    f1_raw = mp["CARRY"]                # for reporting bias
    print(f"  range: {front.index.min().date()} → {front.index.max().date()}, n={len(front)}")
    print(f"  Spot VIX (CBOE ^VIX):               mean={front.mean():.2f}  median={front.median():.2f}")
    print(f"  F1 raw (CARRY column):              mean={f1_raw.mean():.2f}  median={f1_raw.median():.2f}")
    print(f"  Bias removed (F1 − spot):           mean={(f1_raw - front).mean():+.3f}  "
          f"median={(f1_raw - front).median():+.3f}")
    print(f"  VIX3M synth (F2/F3 → 93d):          mean={vix3m.mean():.2f}  median={vix3m.median():.2f}")
    print(f"  contango pct: {(front < vix3m).mean()*100:.1f}%   "
          f"backwardation pct: {(front > vix3m).mean()*100:.1f}%")

    # -------- 2. eVRP from GARCH(1,1) walk-forward vol forecast --------
    print(f"\n[2/5] Computing eVRP from GARCH(1,1) (fit window={GARCH_FIT_WINDOW}d, "
          f"refit every {GARCH_REFIT_EVERY}d)...")
    spy = pd.read_parquet(SP500_PATH).squeeze().dropna().resample("1B").last().ffill()
    eVRP, eRV30 = compute_eVRP(spy, front)
    print(f"  eRV30 (GARCH %):    mean={eRV30.mean():.2f}  std={eRV30.std():.2f}  "
          f"min={eRV30.min():.2f}  max={eRV30.max():.2f}")
    print(f"  eVRP (vol-points):  mean={eVRP.mean():+.2f}  std={eVRP.std():.2f}  "
          f"positive pct={(eVRP > 0).mean()*100:.1f}%")

    # -------- 3. Regime gating + continuous target vol --------
    print("\n[3/5] Applying regime logic + continuous target_vol = clip(VIX/100, MAX)...")
    common = front.index.intersection(vix3m.index).intersection(eVRP.index)
    sized = regime_and_target_vol(front.reindex(common), vix3m.reindex(common), eVRP.reindex(common))
    regime_counts = sized["regime"].value_counts()
    print(f"  Regime distribution:")
    for r in ["short_full", "short_half", "long_full", "flat"]:
        n = regime_counts.get(r, 0)
        pct = n / len(sized) * 100
        avg_target = sized.loc[sized["regime"] == r, "target_vol"].mean()
        print(f"    {r:<12} n={n:>5}  ({pct:5.1f}%)  avg target_vol = {avg_target*100:.1f}%")

    # -------- 4. Vol-of-vol sizing → contracts --------
    print("\n[4/5] Vol-of-vol sizing → contracts...")
    adj = pd.read_parquet(ADJ_PATH).squeeze().dropna().resample("1B").last().ffill()
    vov = vol_of_vol_per_contract(adj)
    common = sized.index.intersection(adj.index).intersection(vov.dropna().index)
    sized = sized.reindex(common)
    front_c = front.reindex(common)
    vov_c = vov.reindex(common)

    target_dollar_vol = sized["direction"] * sized["target_vol"] * CAPITAL
    target_contracts_float = target_dollar_vol / vov_c
    target_contracts = target_contracts_float.round()
    held = apply_rebalance_threshold(target_contracts, front_c, CAPITAL, REBAL_THRESHOLD_PCT)
    print(f"  Avg vol-of-vol per contract (annual $): ${vov_c.mean():,.0f}")
    print(f"  Avg held |contracts|: {held.abs().mean():.2f}  Max: {int(held.abs().max())}")

    # -------- 5. P&L on back-adjusted price (continuous, no roll bookkeeping) --------
    print("\n[5/5] Computing P&L on back-adjusted VIX...")
    adj_c = adj.reindex(common)

    daily_dollar_change = adj_c.diff() * VIX_MULTIPLIER
    gross_pnl = held.shift(1).fillna(0) * daily_dollar_change
    trades = held.diff().abs().fillna(held.abs())
    cost_per_contract = VIX_PERBLOCK_COMMISSION + VIX_SPREAD_PTS * VIX_MULTIPLIER
    costs = trades * cost_per_contract
    net_pnl = gross_pnl - costs

    valid = net_pnl.dropna()
    valid = valid[valid.index >= valid.index[15]]  # skip warmup window
    held = held.reindex(valid.index)
    sized_v = sized.reindex(valid.index)

    # =================================================================
    print("\n" + "=" * 110)
    print(f"\nFull sample ({valid.index.min().date()} → {valid.index.max().date()}, n={len(valid)}):")
    _print_stats(_stats_block(valid, CAPITAL, "FULL (net)"))
    _print_stats(_stats_block(gross_pnl.reindex(valid.index), CAPITAL, "GROSS (no costs)"))

    oos = valid[valid.index >= OOS_START]
    if len(oos) > 50:
        print(f"\nOOS 2024-2026 ({oos.index.min().date()} → {oos.index.max().date()}, n={len(oos)}):")
        _print_stats(_stats_block(oos, CAPITAL, "OOS"))

    # By year
    print(f"\nPer-year breakdown:")
    print(f"  {'Year':<6} {'n':>4}  {'SR':>7}  {'AnnRet%':>8}  {'AnnVol%':>8}  {'$P&L':>14}  {'MaxDD%':>8}")
    for yr, sub in valid.groupby(valid.index.year):
        if len(sub) < 50:
            continue
        s = _stats_block(sub, CAPITAL, str(yr))
        if "sharpe" not in s:
            continue
        print(f"  {yr:<6} {s['n']:>4}  {s['sharpe']:>+7.3f}  {s['ann_mean_pct']:>+7.2f}%  "
              f"{s['ann_std_pct']:>7.2f}%  ${s['ann_mean_dollar']:>+12,.0f}  {s['max_dd_pct']:>+7.2f}%")

    # P&L by regime
    print(f"\nP&L by regime (where regime is what we WERE IN):")
    pnl_with_regime = pd.concat([valid.rename("pnl"), sized_v["regime"]], axis=1).dropna()
    for r in ["short_full", "short_half", "long_full", "flat"]:
        sub = pnl_with_regime[pnl_with_regime["regime"] == r]["pnl"]
        if len(sub) < 5:
            continue
        s = _stats_block(sub, CAPITAL, r)
        print(f"  {r:<12} n={s['n']:>5}  total $P&L=${sub.sum():>+10,.0f}  "
              f"avg/day=${sub.mean():>+8.0f}  hit={s['hit_rate']:.1f}%")

    # Costs
    abs_gross = gross_pnl.reindex(valid.index).abs().sum()
    total_costs = costs.reindex(valid.index).sum()
    if abs_gross > 0:
        print(f"\nCosts: ${total_costs:,.0f} / |Gross P&L|=${abs_gross:,.0f} = {total_costs/abs_gross*100:.1f}%")

    # Position breakdown
    pct_long = float((held > 0).mean() * 100)
    pct_short = float((held < 0).mean() * 100)
    pct_flat = float((held == 0).mean() * 100)
    print(f"\nPosition exposure: long={pct_long:.1f}%  short={pct_short:.1f}%  flat={pct_flat:.1f}%")
    print(f"  max abs position: {int(held.abs().max())} contracts")
    annual_trades = trades.reindex(valid.index).sum() / len(valid) * 252
    print(f"  annual contract turnover: {annual_trades:.1f}")

    # SPY correlation
    print(f"\nCorrelation with SP500 buy-and-hold:")
    spy_pct = spy.pct_change().reindex(valid.index)
    pnl_pct = valid / CAPITAL
    common_idx = spy_pct.dropna().index.intersection(pnl_pct.dropna().index)
    if len(common_idx) > 100:
        corr = pnl_pct.reindex(common_idx).corr(spy_pct.reindex(common_idx))
        print(f"  full sample (n={len(common_idx)}): {corr:+.3f}")
        oos_idx = common_idx[common_idx >= OOS_START]
        if len(oos_idx) > 50:
            corr_oos = pnl_pct.reindex(oos_idx).corr(spy_pct.reindex(oos_idx))
            print(f"  OOS 2024-26     (n={len(oos_idx)}): {corr_oos:+.3f}")

    # Save
    valid.rename("net_pnl_usd").to_csv("/tmp/vix_contango_pnl.csv")
    pd.DataFrame({
        "vix": sized_v["vix"], "vix3m": sized_v["vix3m"], "eVRP": sized_v["eVRP"],
        "regime": sized_v["regime"], "target_vol": sized_v["target_vol"],
        "vol_of_vol_$": vov_c.reindex(valid.index),
        "held_contracts": held, "gross_pnl": gross_pnl.reindex(valid.index),
        "cost": costs.reindex(valid.index), "net_pnl": valid,
    }).to_csv("/tmp/vix_contango_full.csv")
    print(f"\nSaved → /tmp/vix_contango_pnl.csv  /tmp/vix_contango_full.csv")


if __name__ == "__main__":
    main()
