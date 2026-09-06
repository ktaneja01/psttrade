"""Find the next 10 instruments to add from Carver's jumbo that are accessible via Barchart."""
import re
from pathlib import Path

ROOT = Path("/Users/kunal.taneja/pysystemtrade")

# Rob's jumbo
rob_cfg = (ROOT / "systems/provided/rob_system/config.yaml").read_text()
m = re.search(r"^forecast_weights:\s*\n(.+?)\n^\w", rob_cfg, re.MULTILINE | re.DOTALL)
rob_jumbo = set(re.findall(r"^  ([A-Z][A-Z0-9_\-]+):\s*$", m.group(1), re.MULTILINE))

# Our databento downloads
dl = (ROOT / "download_databento.py").read_text()
m2 = re.search(r"INSTRUMENTS\s*=\s*\{(.+?)\n\}", dl, re.DOTALL)
databento = set(re.findall(r'"([A-Za-z][A-Za-z0-9_\-]+)":', m2.group(1)))

# Our current bc-utils downloads (from private_config.yaml)
bcu = (ROOT.parent / "bc-utils/private_config.yaml").read_text() if (ROOT.parent / "bc-utils/private_config.yaml").exists() else ""
if not bcu:
    bcu_path = Path("/Users/kunal.taneja/bc-utils/private_config.yaml")
    if bcu_path.exists():
        bcu = bcu_path.read_text()
bcutils_downloaded = set(re.findall(r"^\s*-\s*([A-Z][A-Z0-9_\-]+)\s*$", bcu, re.MULTILINE))

# Our raw asset classes in signals.py (what we've tried to trade)
sig = (ROOT / "signals.py").read_text()
m3 = re.search(r"_raw_asset_classes\s*=\s*\{(.+?)^\}", sig, re.MULTILINE | re.DOTALL)
our_raw = set(re.findall(r'"([A-Za-z][A-Za-z0-9_\-]+)"', m3.group(1)))

# Rob's jumbo - instruments NOT downloaded anywhere and NOT in our universe
rob_missing_completely = rob_jumbo - databento - bcutils_downloaded - our_raw

# Split by likely data source
# Eurex / European / Asian — bc-utils candidates
likely_bcutils = {
    # Bonds
    "BUXL", "OAT", "BTP", "BTP3", "BONO", "CH10",
    # Equity indices (non-US)
    "AEX", "SMI", "MIB", "KOSPI", "HANG", "NIFTY", "TAIEX", "ASX",
    "NIKKEI-JPY", "VNKI", "BOVESPA",
    # ICE Europe
    "BRENT_CRUDE",
    # Short rates / IR
    "EURIBOR", "SONIA3",
    # Cboe Volatility / swaps
    # Commodities with ICE/LME presence
    "TIN_LME",
    # FX crosses on CME that we don't have
    "SGD", "NOK", "SEK", "TWD", "CLP", "CZK",
    "EURAUD", "EURCAD", "GBPCHF", "GBPJPY", "AUDJPY", "CHFJPY",
    # Asian rates
    "JGB", "KR10", "KR3",
    # Misc commodity
    "BBCOMM",
}

# Exclude ones we've already added or have
likely_missing = rob_missing_completely & likely_bcutils

print("=" * 70)
print("INSTRUMENTS IN ROB'S JUMBO, NOT YET DOWNLOADED (any source)")
print("=" * 70)
print(f"Total missing: {len(rob_missing_completely)}")
print()
print("Likely available via Barchart (excluding our existing sources):")
for inst in sorted(likely_missing):
    # Check if has pysystemtrade config
    inst_cfg = Path("/Users/kunal.taneja/pysystemtrade/data/futures/csvconfig/instrumentconfig.csv").read_text()
    row = [line for line in inst_cfg.split("\n") if line.startswith(inst + ",")]
    config_status = row[0].split(",")[4] if row else "NO CONFIG"
    print(f"  {inst:<18s}  class: {config_status}")

print()
print(f"Current private_config.yaml downloads:")
if bcu:
    m = re.search(r"barchart_download_list:(.+?)(?=^[a-z_]+:|\Z)", bcu, re.MULTILINE | re.DOTALL)
    if m:
        items = re.findall(r"^\s*-\s*([A-Z][A-Z0-9_\-]+)\s*(#.*)?$", m.group(1), re.MULTILINE)
        for inst, _ in items:
            print(f"  {inst}")

# Pick priority 10
priority_10 = [
    "BUXL",       # 30yr German bond — bond diversification
    "OAT",        # French 10yr — bond diversification
    "BTP",        # Italian 10yr — peripheral bond
    "BRENT_CRUDE", # ICE Brent (we have NYMEX version via Databento)
    "NIKKEI-JPY", # Osaka Nikkei (Yen denom, different from CME NKD)
    "AEX",        # Dutch equity index
    "SMI",        # Swiss Market Index
    "HANG",       # Hang Seng — Asian equity
    "KOSPI",      # Korean equity
    "EURIBOR",    # Short-term Euro rate
]

# Filter to ones with configs
priority_with_configs = []
inst_cfg = Path("/Users/kunal.taneja/pysystemtrade/data/futures/csvconfig/instrumentconfig.csv").read_text()
for inst in priority_10:
    row = [line for line in inst_cfg.split("\n") if line.startswith(inst + ",")]
    if row:
        priority_with_configs.append((inst, row[0]))

print()
print("=" * 70)
print("PROPOSED NEXT 10 for barchart download (in priority order):")
print("=" * 70)
for inst, row in priority_with_configs:
    parts = row.split(",")
    print(f"  {inst:<18s}  {parts[4]:<10s}  {parts[3]:<5s}  {parts[1][:40]}")
