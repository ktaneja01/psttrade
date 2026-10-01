from sysdata.config.configdata import Config
from sysdata.data_blob import dataBlob
from sysdata.sim.futures_sim_data_with_data_blob import genericBlobUsingFuturesSimData
from sysdata.csv.csv_instrument_data import csvFuturesInstrumentData
from sysdata.csv.csv_roll_parameters import csvRollParametersData
from sysdata.csv.csv_spread_costs import csvSpreadCostData
from sysdata.csv.csv_spot_fx import csvFxPricesData
from sysdata.parquet.parquet_multiple_prices import parquetFuturesMultiplePricesData
from sysdata.parquet.parquet_adjusted_prices import parquetFuturesAdjustedPricesData
from syslogging.logger import get_logger
from systems.basesystem import System
from systems.forecasting import Rules
from systems.rawdata import RawData
from systems.provided.rob_system.rawdata import myFuturesRawData
from systems.forecast_combine import ForecastCombine
from systems.forecast_scale_cap import ForecastScaleCap
from systems.provided.attenuate_vol.vol_attenuation_forecast_scale_cap import (
    volAttenForecastScaleCap,
)
from systems.positionsizing import PositionSizing
from systems.portfolio import Portfolios
from systems.accounts.accounts_stage import Account
from systems.provided.dynamic_small_system_optimise.optimised_positions_stage import (
    optimisedPositions,
)
from systems.provided.dynamic_small_system_optimise.accounts_stage import (
    accountForOptimisedStage,
)
from sysquant.optimisation.weights import portfolioWeights as _pw
from syscore.constants import arg_not_supplied as _ans

# Max single-instrument concentration cap in the dyn-optimiser: no bet larger than
# MAX_POSITION_FRAC of capital. Uses the SHIPPED maximum_positions mechanism (the
# greedy solver enforces it per-instrument, in contracts): max_contracts =
# MAX_POSITION_FRAC / per_contract_value. Prevents e.g. inverse-correlated names
# (VIX/V2X/DX) from taking an outsized share of the book at the position layer.
MAX_POSITION_FRAC = 0.80   # L=0.8: max notional per instrument = 0.8x capital (worst-20d-move drawdown-derived)

class optimisedPositionsCapped(optimisedPositions):
    def get_optimal_positions_with_fixed_contract_values(
        self, relevant_date=_ans, previous_positions=_ans, maximum_positions=_ans):
        if maximum_positions is _ans:
            pcv = self.get_per_contract_value(relevant_date)  # {inst: value as frac of capital}
            maxpos = {}
            for code, v in dict(pcv).items():
                try:
                    maxpos[code] = MAX_POSITION_FRAC / v if v and v > 0 else 1e9
                except Exception:
                    maxpos[code] = 1e9
            maximum_positions = _pw(maxpos)
        return super().get_optimal_positions_with_fixed_contract_values(
            relevant_date=relevant_date, previous_positions=previous_positions,
            maximum_positions=maximum_positions)


class parquetFuturesSimData(genericBlobUsingFuturesSimData):
    """Sim data: Parquet for multiple/adjusted prices, CSV for everything else."""
    def __init__(self):
        data = dataBlob(
            log=get_logger("parquetFuturesSimData"),
            class_list=[
                parquetFuturesAdjustedPricesData,
                parquetFuturesMultiplePricesData,
                csvFuturesInstrumentData,
                csvFxPricesData,
                csvRollParametersData,
                csvSpreadCostData,
            ],
        )
        super().__init__(data=data)

import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
from scipy.spatial.distance import squareform

# Bad markets from Carver's Remove_markets_report (14/04/2026):
#   too safe (ann vol < 5%): US2, US3, US5, EURCHF, GBPEUR, CAD, SOFR1
#   not enough risk volume:  LUMBER-new, OATIES
#   too expensive:           STEEL
bad_markets = {"GBPJPY",  # never fills at $500K + weak (cross, risk-on proxy)
               "US2", "US3", "US5", "EURCHF", "GBPEUR", "CAD", "SOFR1",
               "LUMBER-new", "OATIES", "STEEL",
               "BRENT_W",
               # SHATZ (1.2%) + BOBL (3.2%) vol < 5% "too safe" floor
               "SHATZ", "BOBL",
               # COTTON2 + SUGAR11 produce -inf P&L under pandl_for_optimised_instrument
               # ~412 days across 10yrs. Standard Account.pandl_for_instrument works fine
               # (+0.34 SR on COTTON2). Likely pysystemtrade dyn-opt bug with ICE softs
               # roll structure. Fix requires library patch.
               "COTTON2", "SUGAR11",
               # EURIBOR too safe (0.5% vol < 5% floor); data ends 2023-05
               "EURIBOR",
               # BTP3 too safe (2.8% vol < 5% floor)
               "BTP3",
               # BRENT-LAST has bad data (NaN vol — zero crossings / gaps)
               "BRENT-LAST",
               # INR recent 2y vol 3.5% — below 5% Carver floor
               "INR",
               # Strict duplicates (corr > 0.95 with another instrument in same class)
               "US10U",  # corr 0.98 with US10
               "US20",   # corr 0.97 with US10U
               "CAC",    # corr 0.97 with EUROSTX
               "DAX",    # corr 0.96 with EUROSTX
               "GAS_US", # corr 0.95 with GAS-LAST
               # Second duplicate pass (5y weekly corr >= 0.92)
               "OAT",    # corr 0.96 with BUND — French rates ≈ German rates
               "BUXL",   # corr 0.92 with BUND — 30y Bund = levered BUND
               "BONO",   # corr 0.95 with BTP — Spanish periph ≈ Italian periph
               # Third duplicate pass (equity cluster, 5y weekly corr > 0.92)
               "SP400",   # corr 0.96 with RUSSELL — mid-cap duplicate
               "NASDAQ",  # corr 0.95 with SP500 — tech-tilted US large-cap
               "DOW",     # corr 0.93 with SP500 — 30-stock US large-cap
               "SPI200",  # only 5yr history (2020-12+), -0.46 SR standalone — too short
               "MSCIWORLD",  # corr 0.94 with SP500 — dominated by US equity
               "DX"}      # corr -0.96 with EUR — DXY is ~58% EUR, redundant
# NOTE: GASOILINE/HEATOIL/OJ/GASOIL/COCOA/HANG/BRE were briefly excluded for
# non-positive back-adjusted prices (additive panama stitch on backwardated
# markets). Restored to the universe after rebuilding their adjusted prices with
# PROPORTIONAL (ratio) back-adjustment, which keeps the series strictly positive
# (16-32% ann vol). See /tmp/rebuild_proportional.py and the Step 0d roll test.

# 6-cluster handcraft allocation — derived from Ward linkage on daily return
# correlations of our 44-instrument universe (see hierarchical_clusters.py, K=6).
#   Grains: 6 pure grain/soy contracts move on crop cycles
#   Energy-Livestock: perishable-commodity cluster (incl RICE, GBPJPY)
#   G10-FX: major currencies, tightly correlated
#   EM-Metal-Crypto: risk-on FX + metals + crypto (all correlate with USD weakness)
_raw_asset_classes = {
    "Bonds":            ["US2", "US3", "US5", "US10", "US10U", "US20", "US30", "SOFR1",
                         "BOBL", "BUND", "SHATZ", "GILT",
                         "BTP", "BUXL", "OAT", "EURIBOR", "BTP3", "BONO",
                         "IG"],   # iBoxx $ IG credit (new credit-spread factor, CFE)
    "Grains":           ["REDWHEAT", "SOYMEAL", "SOYOIL", "WHEAT", "CORN", "SOYBEAN", "OATIES",
                         # New 10yr addition (barchart ICE-CA):
                         "CANOLA"],
    "Energy-Livestock": ["CRUDE_W_micro", "BRENT_W", "GAS_US", "GASOILINE", "HEATOIL", "GAS_US_mini",
                         "LIVECOW", "FEEDCOW", "LEANHOG", "RICE", "LUMBER-new", "GBPJPY",
                         # softs + gasoil from bc-utils (10yr, ICE).
                         # COTTON2 + SUGAR11 produce -inf under dyn opt (data bug)
                         "COFFEE", "OJ", "GASOIL", "COCOA",
                         # New 10yr additions (barchart ICE):
                         "EUA", "ROBUSTA",
                         # New breadth (barchart SGX, ~2yr): TSR20 rubber
                         "RUBBER"],
    # VIX/V2X fold into Equity-Risk (inverse-correlation hedge; gets small
    # inverse-vol weight due to high realized vol, 5% cap applies)
    "Equity-Risk":      ["SP500_micro", "NASDAQ", "RUSSELL", "DOW", "NIKKEI", "SP400",
                         "CAC", "DAX", "EUROSTX", "FTSE100",
                         "VIX",
                         "AEX_mini", "HANG_mini", "SMI", "MSCIWORLD", "SPI200",
                         "TECDAX",
                         # New breadth (barchart, 2018+ unless noted):
                         # EU sector sub-indices + US real estate + eurostx small
                         "EU-BANKS", "EU-BASIC", "EU-INSURE", "EUROSTX-SMALL",
                         "US-REALESTATE",
                         # New EU sectors (EUREX, 2018+, 17-28% vol):
                         "EU-TECH", "EU-HEALTH", "EU-OIL", "EU-AUTO",
                         "EU-MEDIA", "EU-DJ-TELECOM", "EU-TRAVEL",
                         # US sectors (bc-utils BM/BN/etc, full 2018-2026 history, 16-32% vol):
                         "US-ENERGY", "US-FINANCE", "US-HEALTH", "US-TECH",
                         "US-INDUSTRY", "US-MATERIAL", "US-STAPLES",
                         # Asian equity (~2yr history): China A50 + MSCI Singapore
                         "FTSECHINAA", "MSCISING"],
    "G10-FX":           ["EUR_micro", "JPY", "GBP_micro", "AUD_micro", "NZD", "CHF", "CAD",
                         "EURCHF", "GBPEUR", "PLN", "EURCAD", "DX",
                         "NOK", "SEK", "INR"],
    "EM-Metal-Crypto":  ["MXP", "ZAR", "BRE",
                         "GOLD_micro", "SILVER-mini", "COPPER-micro", "PLAT", "PALLAD", "STEEL",
                         "BITCOIN", "ETHER-micro",
                         # New 10yr LME additions:
                         "ALUMINIUM_LME", "ZINC_LME",
                         # New breadth (barchart SGX, ~2yr): TSI iron ore
                         "IRON"],
}
asset_classes = {c: [i for i in insts if i not in bad_markets]
                 for c, insts in _raw_asset_classes.items()}
N_TARGET_CLASSES = 6  # 6 clusters, each gets 16.67% of risk budget


def realized_vol(instrument_code: str) -> float:
    """Annualized % return vol, computed from recent data (last ~2 years)
    to avoid back-adjusted prices crossing zero."""
    path = f"/usr/local/bc_data/futures_adjusted_prices/{instrument_code}.parquet"
    df = pd.read_parquet(path)
    s = df.squeeze() if df.shape[1] == 1 else df.iloc[:, 0]
    s = s.dropna().resample("1B").last().dropna()
    # Use only recent data where prices are still positive and realistic
    recent = s.tail(500)
    recent = recent[recent > 0]
    rets = recent.pct_change().dropna()
    return float(rets.std() * np.sqrt(252))


# HERC (Hierarchical Equal Risk Contribution) weighting with 5% cap
MAX_WEIGHT = 0.05

all_instruments = [i for insts in asset_classes.values() for i in insts]


def daily_returns(instrument_code: str) -> pd.Series:
    """Recent daily returns from adjusted prices."""
    path = f"/usr/local/bc_data/futures_adjusted_prices/{instrument_code}.parquet"
    df = pd.read_parquet(path)
    s = df.squeeze() if df.shape[1] == 1 else df.iloc[:, 0]
    s = s.dropna().resample("1B").last().dropna().tail(500)
    s = s[s > 0]
    rets = s.pct_change().dropna()
    rets.name = instrument_code
    return rets


# Build returns matrix
returns_df = pd.concat([daily_returns(i) for i in all_instruments], axis=1)
returns_df = returns_df.dropna(how="all")

# Vols and correlations
instrument_vols = {i: float(returns_df[i].std() * np.sqrt(252)) for i in all_instruments}
corr_matrix = returns_df.corr()


def estimate_sr_cost_per_trade(inst: str, spread_costs: dict, instrument_vols: dict) -> float:
    """Approximate SR cost per round-trip trade (Carver's 0.01 filter metric).
    Per-trade cost = (spread × pointsize) / annual_$_vol_per_contract.
    This is regime-invariant: same market, same cost regardless of rule turnover.
    """
    sc = max(spread_costs.get(inst, 0.01), 1e-6)
    v = instrument_vols.get(inst, 0.2)
    inst_cfg = pd.read_csv(
        "/Users/kunal.taneja/pysystemtrade/data/futures/csvconfig/instrumentconfig.csv"
    )
    cfg_row = inst_cfg[inst_cfg["Instrument"] == inst]
    if cfg_row.empty:
        return float("nan")
    pointsize = float(cfg_row["Pointsize"].iloc[0])
    try:
        path = f"/usr/local/bc_data/futures_adjusted_prices/{inst}.parquet"
        df = pd.read_parquet(path)
        s = df.squeeze() if df.shape[1] == 1 else df.iloc[:, 0]
        avg_price = float(s.dropna().tail(500).abs().mean())
    except Exception:
        avg_price = 100.0
    dollar_vol_per_contract = avg_price * pointsize * v
    if dollar_vol_per_contract <= 0:
        return float("nan")
    return (sc * pointsize) / dollar_vol_per_contract  # per-trade, no turnover factor


def load_spread_costs() -> dict:
    """Read spread costs from the pysystemtrade CSV."""
    df = pd.read_csv(
        "/Users/kunal.taneja/pysystemtrade/data/futures/csvconfig/spreadcosts.csv"
    )
    return dict(zip(df["Instrument"], df["SpreadCost"]))


def cap_weights(raw: dict, cap: float) -> dict:
    """Iteratively cap weights at `cap` and redistribute to uncapped."""
    w = dict(raw)
    while True:
        over = {k: v for k, v in w.items() if v > cap}
        if not over:
            break
        excess = sum(v - cap for v in over.values())
        under = {k: v for k, v in w.items() if v <= cap}
        if not under:
            break
        under_total = sum(under.values())
        for k in over:
            w[k] = cap
        for k in under:
            w[k] += excess * (under[k] / under_total)
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}


# ============================================================
# Weighting: 1/7 risk budget per asset class, inverse-vol within class,
#            per-trade SR cost filter at 0.01 (Carver's threshold)
# ============================================================
MAX_SR_COST_PER_TRADE = 0.01   # Carver's MAX_SR_COST
spread_costs = load_spread_costs()

print(f"=== Per-trade SR cost filter (threshold = {MAX_SR_COST_PER_TRADE}) ===")
eligible_by_class = {}
dropped = []
for cls, insts in asset_classes.items():
    eligible_by_class[cls] = []
    for inst in insts:
        sr = estimate_sr_cost_per_trade(inst, spread_costs, instrument_vols)
        if sr <= MAX_SR_COST_PER_TRADE or pd.isna(sr):
            eligible_by_class[cls].append(inst)
        else:
            dropped.append((inst, sr))
            print(f"  DROP {inst}: per-trade SR cost ≈ {sr:.4f} > {MAX_SR_COST_PER_TRADE}")

if not dropped:
    print("  (nothing dropped — all SR costs within threshold)")

# Step 2: Each asset class gets 1/N_CLASSES of risk budget.
# Step 3: Within class, inverse-vol weighted = 1/N equal risk per instrument
# NOTE: actual runtime weights come from handcraft_shrunk via the estimator below.
# This is a fallback for establishing the universe.
class_budget = 1.0 / N_TARGET_CLASSES
raw_weights = {}
for cls, insts in eligible_by_class.items():
    if not insts:
        continue
    inv_vols = {i: 1.0 / max(instrument_vols[i], 1e-6) for i in insts}
    total_inv = sum(inv_vols.values())
    for i in insts:
        raw_weights[i] = class_budget * inv_vols[i] / total_inv

# Step 4: Safety cap at 5% per instrument (redistributes within deployed budget)
deployed = sum(raw_weights.values())  # should be ~6/7 if one class empty
if deployed > 0:
    # Scale to 1.0 for capping math, then scale back
    scaled = {k: v / deployed for k, v in raw_weights.items()}
    capped = cap_weights(scaled, MAX_WEIGHT / deployed)  # cap relative to deployed
    instrument_weights = {k: v * deployed for k, v in capped.items()}
else:
    instrument_weights = {}
instruments = list(instrument_weights.keys())

non_empty = sum(1 for insts in eligible_by_class.values() if insts)
cash_budget = (N_TARGET_CLASSES - non_empty) * class_budget
print(f"\n=== Handcraft + correlation shrinkage (fallback: 1/{N_TARGET_CLASSES} per class) ===")
print(f"    Active classes: {non_empty}/{N_TARGET_CLASSES}  |  "
      f"Deployed: {deployed*100:.1f}%  |  Cash: {cash_budget*100:.1f}%")
for cls, insts in asset_classes.items():
    eligible = eligible_by_class.get(cls, [])
    cls_total = sum(instrument_weights.get(i, 0.0) for i in eligible)
    tag = f"(empty → 1/{N_TARGET_CLASSES} cash)" if not eligible else f"({len(eligible)} instruments, class total = {cls_total*100:.2f}%)"
    print(f"\n{cls} {tag}:")
    for i in sorted(eligible, key=lambda x: -instrument_weights.get(x, 0)):
        raw_w = raw_weights.get(i, 0) * 100
        final_w = instrument_weights.get(i, 0) * 100
        cap_tag = " [CAPPED]" if raw_weights.get(i, 0) > MAX_WEIGHT else ""
        sr = estimate_sr_cost_per_trade(i, spread_costs, instrument_vols)
        print(f"  {i:12s}  vol={instrument_vols.get(i, 0)*100:5.1f}%  "
              f"SR_cost≈{sr:.3f}  raw={raw_w:5.2f}%  final={final_w:5.2f}%{cap_tag}")

print(f"\nTotal: {len(instruments)} instruments, weight sum = {sum(instrument_weights.values()):.4f}")
if dropped:
    print(f"Dropped {len(dropped)} over {MAX_SR_COST_PER_TRADE} per-trade SR cost threshold")
print()

# ============================================================
# Config + system build, Carver's way (no reinvention):
#   * config  -> production/live/production_config.yaml (single source of truth)
#   * builder -> systems.provided.rob_system.run_system.futures_system (shipped;
#                exact stages: optimisedPositions + myFuturesRawData + volAtten...)
# The FROZEN dicts / rule groups above remain the SOURCE for regenerating that YAML
# (see production/MIGRATION_TO_STOCK.md); the live system trades off the YAML.
# ============================================================
from systems.provided.rob_system.run_system import futures_system

system = futures_system(
    sim_data=parquetFuturesSimData(),
    config_filename="production.live.production_config.yaml",
)
config = system.config
# helpers used by the diagnostics below, taken from the loaded (pruned 114) config
instruments = config.instruments
asset_classes = config.asset_classes

# ============================================================
# Per-instrument × per-rule SR cost + turnover diagnostic
# (pysystemtrade's accurate cost calculation, not my rough estimate)
# ============================================================
instrument_to_class = {}
for cls, insts in asset_classes.items():
    for i in insts:
        instrument_to_class[i] = cls

print("\n=== Per-rule tradeability check (SR cost threshold = 0.10) ===")
print(f"{'Instrument':12s}  {'Class':10s}  ", end="")
rule_names = list(config.forecast_weights.keys())
for r in rule_names:
    print(f"{r:>14s}", end="")
print(f"  {'worst':>8s}  {'tradeable':>10s}")

tradeable_count = {"total": 0, "all_rules_drop": 0, "some_rules_drop": 0, "all_rules_ok": 0}
for inst in instruments:
    cls = instrument_to_class.get(inst, "?")
    print(f"{inst:12s}  {cls:10s}  ", end="")
    costs = []
    for r in rule_names:
        try:
            sr_cost = system.accounts.get_SR_cost_for_instrument_forecast(inst, r)
            turnover = system.accounts.forecast_turnover(inst, r)
            costs.append(sr_cost)
            marker = "x" if sr_cost > 0.10 else " "
            print(f"{sr_cost:>8.3f}(t{turnover:>3.1f}){marker}", end="")
        except Exception:
            costs.append(float("nan"))
            print(f"{'N/A':>14s}", end="")
    worst = max((c for c in costs if not pd.isna(c)), default=float("nan"))
    n_drop = sum(1 for c in costs if not pd.isna(c) and c > 0.10)
    if n_drop == 0:
        verdict = "all OK"
        tradeable_count["all_rules_ok"] += 1
    elif n_drop == len(rule_names):
        verdict = "all DROP"
        tradeable_count["all_rules_drop"] += 1
    else:
        verdict = f"{n_drop}/{len(rule_names)} drop"
        tradeable_count["some_rules_drop"] += 1
    tradeable_count["total"] += 1
    print(f"  {worst:>8.3f}  {verdict:>10s}")

print(f"\nSummary: {tradeable_count['all_rules_ok']}/{tradeable_count['total']} "
      f"instruments have ALL rules under 0.10 SR cost")
print(f"         {tradeable_count['some_rules_drop']}/{tradeable_count['total']} "
      f"have SOME rules dropped")
print(f"         {tradeable_count['all_rules_drop']}/{tradeable_count['total']} "
      f"have ALL rules dropped (no trading)")
print("(format: SR_cost(turnover_per_year); 'x' marks cost > 0.10)")

print("\n=== Latest signals ===")
print(f"{'Instrument':12s}  {'Combined Fcst':>14s}  {'OptPos':>10s}")
for instrument in instruments:
    combined = system.combForecast.get_combined_forecast(instrument)
    position = system.accounts.get_optimised_position(instrument)
    print(f"{instrument:12s}  {combined.iloc[-1]:+14.2f}  {position.iloc[-1]:+10.0f}")

print("\n\n=== BACKTEST P&L (dynamic-optimised portfolio) ===")
pnl = system.accounts.optimised_portfolio()
print(pnl.stats())

# ============================================================
# Per-instrument and per-asset-class Sharpe (trend-only)
# ============================================================
print("\n\n=== Per-instrument Sharpe (trend-only) ===")
print(f"{'Instrument':12s}  {'Class':10s}  {'Sharpe':>8s}  {'Ann $':>10s}  {'Ann std':>10s}")

instrument_to_class = {}
for cls, insts in asset_classes.items():
    for i in insts:
        instrument_to_class[i] = cls

per_instrument = {}
for inst in instruments:
    try:
        p = system.accounts.pandl_for_optimised_instrument(inst)
        stats = dict(p.stats()[0])
        per_instrument[inst] = {
            "sharpe":   float(stats.get("sharpe", 0) or 0),
            "ann_mean": float(stats.get("ann_mean", 0) or 0),
            "ann_std":  float(stats.get("ann_std", 0) or 0),
            "class":    instrument_to_class.get(inst, "?"),
        }
    except Exception:
        per_instrument[inst] = {"sharpe": float("nan"), "ann_mean": 0, "ann_std": 0,
                                "class": instrument_to_class.get(inst, "?")}

sorted_by_sharpe = sorted(
    per_instrument.items(),
    key=lambda kv: -kv[1]["sharpe"] if not np.isnan(kv[1]["sharpe"]) else -999,
)
for inst, d in sorted_by_sharpe:
    print(f"{inst:12s}  {d['class']:10s}  {d['sharpe']:>+8.3f}  {d['ann_mean']:>+10.0f}  {d['ann_std']:>10.0f}")

print("\n\n=== Per-asset-class Sharpe (trend+carry) ===")
print(f"{'Class':14s}  {'# inst':>6s}  {'Mean SR':>8s}  {'Median SR':>10s}  "
      f"{'SR stdev':>9s}  {'SR skew':>8s}  {'Min SR':>8s}  {'Max SR':>8s}  "
      f"{'Total Ann $':>12s}  {'Positive':>10s}")

from scipy.stats import skew as scipy_skew
for cls, insts in asset_classes.items():
    class_data = [per_instrument[i] for i in insts if i in per_instrument]
    if not class_data:
        continue
    sharpes = [d["sharpe"] for d in class_data if not np.isnan(d["sharpe"])]
    if not sharpes:
        continue
    mean_s = float(np.mean(sharpes))
    median_s = float(np.median(sharpes))
    std_s = float(np.std(sharpes)) if len(sharpes) > 1 else 0.0
    skew_s = float(scipy_skew(sharpes)) if len(sharpes) > 2 else 0.0
    min_s = float(np.min(sharpes))
    max_s = float(np.max(sharpes))
    total_ann = float(np.sum([d["ann_mean"] for d in class_data]))
    pos = sum(1 for s in sharpes if s > 0)
    print(f"{cls:14s}  {len(sharpes):>6d}  {mean_s:>+8.3f}  {median_s:>+10.3f}  "
          f"{std_s:>9.3f}  {skew_s:>+8.3f}  {min_s:>+8.3f}  {max_s:>+8.3f}  "
          f"{total_ann:>+12.0f}  {pos:>3d}/{len(sharpes):<3d}")

# ============================================================
# Per-class × per-rule Sharpe (mean & median across instruments in class)
# ============================================================
print("\n\n=== Per-class × per-rule Sharpe (mean / median across instruments) ===")
print(f"{'Class':14s}  {'# inst':>6s}  ", end="")
for r in rule_names:
    print(f"{r:>20s}", end="")
print()

rule_returns_by_class = {cls: {r: [] for r in rule_names} for cls in asset_classes}

for inst in instruments:
    cls = instrument_to_class.get(inst, "?")
    for r in rule_names:
        try:
            p = system.accounts.pandl_for_instrument_forecast(inst, r)
            stats = dict(p.stats()[0])
            sr = float(stats.get("sharpe", 0) or 0)
            if not np.isnan(sr):
                rule_returns_by_class[cls][r].append(sr)
        except Exception:
            pass

for cls in asset_classes:
    sharpes_by_rule = rule_returns_by_class[cls]
    n = max((len(v) for v in sharpes_by_rule.values()), default=0)
    print(f"{cls:14s}  {n:>6d}  ", end="")
    for r in rule_names:
        vals = sharpes_by_rule[r]
        if vals:
            print(f"  {np.mean(vals):+6.2f}/{np.median(vals):+6.2f}  ", end="")
        else:
            print(f"{'—':>20s}", end="")
    print()
print("(format: mean_Sharpe / median_Sharpe across instruments in class)")

# ============================================================
# Carry performance by calendar year × asset class
# (composite carry = equal-weight across 4 carry speeds per instrument)
# ============================================================
print("\n\n=== Carry P&L by calendar year × asset class (Sharpe) ===")
carry_rule_names = [r for r in rule_names if r.startswith("carry")]

carry_daily_by_class = {}
for cls, insts in asset_classes.items():
    inst_series = []
    for inst in insts:
        if inst not in instruments:
            continue
        carry_pnls = []
        for r in carry_rule_names:
            try:
                p = system.accounts.pandl_for_instrument_forecast(inst, r)
                carry_pnls.append(p.as_ts)
            except Exception:
                pass
        if carry_pnls:
            avg = pd.concat(carry_pnls, axis=1).mean(axis=1)
            inst_series.append(avg)
    if inst_series:
        carry_daily_by_class[cls] = pd.concat(inst_series, axis=1).mean(axis=1)

years = sorted({y for ts in carry_daily_by_class.values() for y in ts.dropna().index.year})
print(f"{'Class':14s}  ", end="")
for y in years:
    print(f"{y:>8d}", end="")
print(f"  {'10y_Sharpe':>10s}")

for cls in asset_classes:
    ts = carry_daily_by_class.get(cls)
    if ts is None:
        continue
    print(f"{cls:14s}  ", end="")
    for y in years:
        yr = ts[ts.index.year == y].dropna()
        if len(yr) > 20 and yr.std() > 0:
            sr = yr.mean() / yr.std() * np.sqrt(252)
            print(f"{sr:>+8.2f}", end="")
        else:
            print(f"{'—':>8s}", end="")
    full = ts.dropna()
    full_sr = full.mean() / full.std() * np.sqrt(252) if full.std() > 0 else 0
    print(f"  {full_sr:>+10.2f}")

print("\n=== Carry P&L by calendar year × asset class (annual $ cumsum) ===")
print(f"{'Class':14s}  ", end="")
for y in years:
    print(f"{y:>9d}", end="")
print()
for cls in asset_classes:
    ts = carry_daily_by_class.get(cls)
    if ts is None:
        continue
    print(f"{cls:14s}  ", end="")
    for y in years:
        yr = ts[ts.index.year == y].dropna()
        total = yr.sum() if len(yr) > 0 else 0
        print(f"{total:>+9.0f}", end="")
    print()

# ============================================================
# Equity curve (trend-only portfolio)
# ============================================================
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

pnl.curve().plot(ax=ax1, color="steelblue", linewidth=1.2)
ax1.set_title("Trend-only Portfolio — Cumulative P&L (10yr)")
ax1.set_ylabel("Cumulative P&L ($)")
ax1.grid(True, alpha=0.3)
ax1.axhline(y=0, color="black", linewidth=0.5)

pnl.drawdown().plot(ax=ax2, color="crimson", linewidth=1.2)
ax2.fill_between(pnl.drawdown().index, pnl.drawdown(), 0, alpha=0.3, color="crimson")
ax2.set_title("Drawdown")
ax2.set_ylabel("Drawdown ($)")
ax2.set_xlabel("Date")
ax2.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig("/tmp/equity_curve.png", dpi=100)
print("\nEquity curve saved to /tmp/equity_curve.png")
