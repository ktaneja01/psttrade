"""Full instrument correlation matrix + IDM walkthrough."""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

INSTS = [  # 54-instrument active universe
    "US10","US30","BUND","GILT","BTP",
    "REDWHEAT","SOYMEAL","SOYOIL","WHEAT","CORN","SOYBEAN",
    "CRUDE_W","GASOILINE","HEATOIL","GAS-LAST","LIVECOW","FEEDCOW","LEANHOG","RICE",
    "GBPJPY","COFFEE","OJ","GASOIL","COCOA",
    "SP500","NIKKEI","EUROSTX","FTSE100","VIX","V2X","AEX","HANG","SMI","RUSSELL",
    "EUR","JPY","GBP","AUD","NZD","CHF","PLN","EURCAD","NOK","SEK",
    "MXP","ZAR","BRE","GOLD","SILVER","COPPER","PLAT","PALLAD","BITCOIN","ETHEREUM",
]

# Weekly returns from adjusted prices
rets = {}
for inst in INSTS:
    s = pd.read_parquet(f"/usr/local/bc_data/futures_adjusted_prices/{inst}.parquet").squeeze()
    s = s.dropna().resample("1B").last().ffill()
    s = s[s > 0]
    r = s.pct_change().dropna()
    r = r[r.index >= "2016-01-01"]
    rets[inst] = r.resample("W").sum()

df = pd.concat(rets, axis=1).dropna(thresh=int(len(INSTS)*0.5))
print(f"{df.index.min().date()} → {df.index.max().date()}  ({len(df)} weekly obs)")

C_raw = df.corr()

# Shrunk (50% toward mean off-diagonal)
iu = np.triu_indices(len(C_raw), k=1)
mean_off = C_raw.values[iu].mean()
C_shrunk = C_raw.values.copy()
for i in range(len(C_shrunk)):
    for j in range(len(C_shrunk)):
        if i != j:
            C_shrunk[i, j] = 0.5 * C_raw.values[i, j] + 0.5 * mean_off
C_shrunk = pd.DataFrame(C_shrunk, index=C_raw.index, columns=C_raw.columns)

print(f"\nMean off-diagonal (raw): {mean_off:.3f}")

# Save CSVs
C_raw.round(3).to_csv("/tmp/corr_raw.csv")
C_shrunk.round(3).to_csv("/tmp/corr_shrunk.csv")
print("Saved /tmp/corr_raw.csv, /tmp/corr_shrunk.csv")

# Plot heatmaps
for tag, M in [("raw", C_raw), ("shrunk", C_shrunk)]:
    fig, ax = plt.subplots(figsize=(16, 14))
    im = ax.imshow(M.values, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(len(M)))
    ax.set_yticks(range(len(M)))
    ax.set_xticklabels(M.columns, rotation=90, fontsize=7)
    ax.set_yticklabels(M.index, fontsize=7)
    plt.colorbar(im, ax=ax, fraction=0.046)
    ax.set_title(f"Instrument correlation matrix ({tag}) — 54 insts, weekly 2016+", fontsize=12)
    plt.tight_layout()
    plt.savefig(f"/tmp/corr_matrix_{tag}.png", dpi=90, bbox_inches="tight")
    plt.close()
    print(f"Saved /tmp/corr_matrix_{tag}.png")

# ==== IDM walkthrough ====
print("\n" + "="*70)
print("IDM STEP-BY-STEP (from current frozen weights)")
print("="*70)

# Frozen handcraft weights from signals.py
W = {
    "GASOIL": 0.025206, "CHF": 0.025206, "VIX": 0.025206, "BITCOIN": 0.025206,
    "JPY": 0.025206, "GASOILINE": 0.025206, "GBPJPY": 0.025206, "RICE": 0.025206,
    "OJ": 0.025206, "WHEAT": 0.025206, "EURCAD": 0.025206, "COFFEE": 0.025206,
    "PALLAD": 0.025206, "BTP": 0.025206, "GOLD": 0.025206, "ETHEREUM": 0.025206,
    "V2X": 0.025206, "SEK": 0.025206, "GBP": 0.025206, "REDWHEAT": 0.025206,
    "COCOA": 0.025206, "CORN": 0.025206,
    "LEANHOG": 0.021629,
    "SOYBEAN": 0.021222, "SOYMEAL": 0.021222,
    "GILT": 0.019762, "BUND": 0.019762,
    "HEATOIL": 0.019393, "GAS-LAST": 0.019393,
    "US10": 0.019379, "US30": 0.019379,
    "CRUDE_W": 0.017288, "SOYOIL": 0.017288,
    "SILVER": 0.016763, "PLAT": 0.016763,
    "PLN": 0.015293, "EUR": 0.015293,
    "NOK": 0.015209, "NIKKEI": 0.014778, "FTSE100": 0.014442,
    "FEEDCOW": 0.012655, "LIVECOW": 0.012655,
    "COPPER": 0.010480, "HANG": 0.010480,
    "BRE": 0.010101,
    "NZD": 0.008807, "AUD": 0.008807,
    "SP500": 0.008563, "RUSSELL": 0.008563,
    "SMI": 0.008228,
    "MXP": 0.006208, "ZAR": 0.006208,
    "EUROSTX": 0.004732, "AEX": 0.004732,
}
w = np.array([W[i] for i in C_raw.columns])
print(f"\nStep 1: weight vector w, sum(w) = {w.sum():.6f}  (must be 1.0)")

# Use shrunk correlation matrix (as pysystemtrade does)
C = C_shrunk.values
print(f"\nStep 2: correlation matrix C (54×54), {np.count_nonzero(C > 0.9)} entries > 0.9")

# Step 3: portfolio variance at unit vol
variance = w @ C @ w
print(f"\nStep 3: w^T C w = {variance:.6f}")

# Step 4: portfolio stdev at unit vol
std = np.sqrt(variance)
print(f"Step 4: sqrt(w^T C w) = {std:.6f}")

# Step 5: IDM = 1 / std
idm_uncapped = 1.0 / std
print(f"\nStep 5: IDM (uncapped) = 1 / {std:.6f} = {idm_uncapped:.3f}")

# Step 6: cap at 2.5
idm = min(idm_uncapped, 2.5)
print(f"Step 6: IDM (capped at 2.5) = {idm:.3f}")

# For comparison, raw IDM
var_raw = w @ C_raw.values @ w
idm_raw_uncapped = 1.0 / np.sqrt(var_raw)
print(f"\nComparison: using RAW correlation (not shrunk)")
print(f"  w^T C_raw w = {var_raw:.6f}")
print(f"  IDM_raw (uncapped) = {idm_raw_uncapped:.3f}")
print(f"  IDM_raw (capped)   = {min(idm_raw_uncapped, 2.5):.3f}")

# ==== FDM walkthrough (theoretical, using forecast weights) ====
print("\n" + "="*70)
print("FDM STEP-BY-STEP (illustrative, using rule weights)")
print("="*70)
rules_family = {
    "TREND (12)":  ["spot_trend8_32","spot_trend16_64","spot_trend32_128","spot_trend64_256",
                    "accel8","accel16","accel32","accel64",
                    "breakout20","breakout40","breakout80","breakout160"],
    "CARRY (12)":  ["carry10","carry30","carry60","carry125","relcarry10","relcarry30",
                    "relcarry60","relcarry125","carry_accel10","carry_accel30",
                    "carry_accel60","carry_accel125"],
    "SKEW (4)":    ["skewabs180","skewabs365","skewrv180","skewrv365"],
}
rule_weight = {}
for rule in rules_family["TREND (12)"]:  rule_weight[rule] = 0.45 / 12
for rule in rules_family["CARRY (12)"]:  rule_weight[rule] = 0.45 / 12
for rule in rules_family["SKEW (4)"]:    rule_weight[rule] = 0.10 / 4
print(f"Forecast weights: trend {0.45/12*100:.2f}% × 12 + carry {0.45/12*100:.2f}% × 12 + "
      f"skew {0.10/4*100:.2f}% × 4 = {sum(rule_weight.values())*100:.0f}% total")
print(f"\nFDM math is analogous to IDM: FDM = 1/sqrt(f^T C_f f), capped at 2.5")
print(f"But requires rule P&L correlation matrix — needs system rebuild (~20 min)")
