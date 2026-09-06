"""YTD 2026 per-class attribution + SPY benchmark comparison."""
import os
os.environ["CAPITAL"] = "500000"

import numpy as np
import pandas as pd

print("Rebuilding system...")
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

CAPITAL = 500_000
YTD_START = "2026-01-01"

# System portfolio YTD
sys_r = pd.Series(system.accounts.portfolio().percent).astype(float) / 100.0
sys_r = sys_r.dropna()
sys_r_ytd = sys_r[sys_r.index >= YTD_START]
sys_pnl_ytd = (sys_r_ytd * CAPITAL).sum()
sys_sharpe_ytd = sys_r_ytd.mean() / sys_r_ytd.std() * np.sqrt(252) if sys_r_ytd.std() > 0 else 0

# SPY (SP500 futures) YTD long-only
spy = pd.read_parquet("/usr/local/bc_data/futures_adjusted_prices/SP500.parquet").squeeze().dropna()
spy = spy.resample("1B").last().ffill()
spy_r = spy.pct_change().dropna()
spy_r_ytd = spy_r[spy_r.index >= YTD_START]
spy_total_ytd = (spy.loc[spy.index >= YTD_START].iloc[-1] / spy.loc[spy.index >= YTD_START].iloc[0] - 1)
spy_sharpe_ytd = spy_r_ytd.mean() / spy_r_ytd.std() * np.sqrt(252) if spy_r_ytd.std() > 0 else 0

# Per-asset-class YTD P&L
raw_asset_classes = {
    "Bonds":            ["US10","US30","BUND","GILT","BTP"],
    "Grains":           ["REDWHEAT","SOYMEAL","SOYOIL","WHEAT","CORN","SOYBEAN"],
    "Energy-Livestock": ["CRUDE_W","GASOILINE","HEATOIL","GAS-LAST","LIVECOW","FEEDCOW",
                         "LEANHOG","RICE","GBPJPY","COFFEE","OJ","GASOIL","COCOA"],
    "Equity-Risk":      ["SP500","NASDAQ","RUSSELL","DOW","NIKKEI","SP400","EUROSTX",
                         "FTSE100","VIX","V2X","AEX","HANG","SMI","MSCIWORLD"],
    "G10-FX":           ["EUR","JPY","GBP","AUD","NZD","CHF","PLN","EURCAD","DX","NOK","SEK"],
    "EM-Metal-Crypto":  ["MXP","ZAR","BRE","GOLD","SILVER","COPPER","PLAT","PALLAD",
                         "BITCOIN","ETHEREUM"],
}

print("\n" + "=" * 90)
print(f"YTD 2026 per-class attribution ({YTD_START} → {sys_r_ytd.index.max().date()})")
print("=" * 90)
print(f"{'Class':<22} {'#inst':>5} {'Mean SR':>8} {'Ann $':>10} {'Pos':>4} {'Neg':>4}")
print("-" * 75)

class_totals = {}
for cls, insts in raw_asset_classes.items():
    sharpes = []
    total_ann = 0
    pos_count = 0
    neg_count = 0
    for inst in insts:
        if inst not in config.instruments:
            continue
        try:
            p = system.accounts.pandl_for_optimised_instrument(inst)
            p_ytd = p[p.index >= YTD_START].dropna()
            if len(p_ytd) < 20 or p_ytd.std() == 0:
                continue
            sr = float(p_ytd.mean() / p_ytd.std() * np.sqrt(252))
            if np.isnan(sr):
                continue
            sharpes.append(sr)
            total_ann += float(p_ytd.mean() * 252)
            if sr > 0: pos_count += 1
            else:      neg_count += 1
        except Exception:
            continue
    if sharpes:
        print(f"{cls:<22} {len(sharpes):>5d} {np.mean(sharpes):>+8.3f} "
              f"{total_ann:>+10.0f} {pos_count:>4d} {neg_count:>4d}")
    class_totals[cls] = total_ann

print(f"\n{'=' * 90}")
print(f"Benchmark comparison YTD 2026")
print(f"{'=' * 90}")
print(f"{'':<22} {'YTD Return':>12} {'YTD Sharpe':>12} {'YTD $ P&L on 500K':>18}")
print("-" * 70)
print(f"{'System (frozen 59)':<22} {sys_pnl_ytd/CAPITAL*100:>+11.2f}% {sys_sharpe_ytd:>+12.3f}   {sys_pnl_ytd:>+16,.0f}")
print(f"{'SPY buy&hold':<22} {spy_total_ytd*100:>+11.2f}% {spy_sharpe_ytd:>+12.3f}   {spy_total_ytd*CAPITAL:>+16,.0f}")

# Correlation to SPY YTD
try:
    df = pd.concat([sys_r_ytd.rename("sys"), spy_r_ytd.rename("spy")], axis=1).dropna()
    corr_ytd = df["sys"].corr(df["spy"])
    print(f"\nSystem ↔ SPY daily corr YTD 2026:  {corr_ytd:+.3f}")
except Exception as e:
    print(f"Corr calc failed: {e}")
