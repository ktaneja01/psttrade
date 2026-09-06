"""Identify instruments that are:
1. In Rob Carver's jumbo portfolio (rob_system/config.yaml forecast_weights)
2. Downloaded via Databento (download_databento.py INSTRUMENTS dict)
3. NOT currently in our signals.py trading universe
"""
import re
from pathlib import Path

ROOT = Path("/Users/kunal.taneja/pysystemtrade")

# 1. Rob Carver's jumbo: instruments with per-instrument forecast_weights blocks
rob_cfg = (ROOT / "systems/provided/rob_system/config.yaml").read_text()
# Find the forecast_weights: section
m = re.search(r"^forecast_weights:\s*\n(.+?)\n^\w", rob_cfg, re.MULTILINE | re.DOTALL)
if not m:
    raise SystemExit("couldn't find forecast_weights section")
fw_block = m.group(1)
rob_jumbo = set(re.findall(r"^  ([A-Z][A-Z0-9_\-]+):\s*$", fw_block, re.MULTILINE))
print(f"Rob's jumbo: {len(rob_jumbo)} instruments")

# 2. Our Databento downloads
dl = (ROOT / "download_databento.py").read_text()
m2 = re.search(r"INSTRUMENTS\s*=\s*\{(.+?)\n\}", dl, re.DOTALL)
our_downloads = set(re.findall(r'"([A-Za-z][A-Za-z0-9_\-]+)":', m2.group(1)))
print(f"Our Databento downloads: {len(our_downloads)} instruments")

# 3. Our currently-traded universe (from signals.py)
sig = (ROOT / "signals.py").read_text()
m3 = re.search(r"_raw_asset_classes\s*=\s*\{(.+?)^\}", sig, re.MULTILINE | re.DOTALL)
raw_block = m3.group(1)
our_raw = set(re.findall(r'"([A-Za-z][A-Za-z0-9_\-]+)"', raw_block))
# Bad markets
m4 = re.search(r"bad_markets\s*=\s*\{(.+?)\}", sig, re.DOTALL)
bad = set(re.findall(r'"([A-Za-z][A-Za-z0-9_\-]+)"', m4.group(1)))
our_traded = our_raw - bad
print(f"Our raw universe: {len(our_raw)}, bad_markets: {len(bad)}, traded: {len(our_traded)}")

# 4. The gap: in Rob's jumbo, in our downloads, NOT in our raw universe
gap = (rob_jumbo & our_downloads) - our_raw
print(f"\n{'=' * 60}")
print(f"MISSING: in Rob's jumbo AND downloaded AND not in our universe")
print(f"{'=' * 60}")
print(f"Count: {len(gap)}")
for inst in sorted(gap):
    print(f"  {inst}")

# 5. Also show: in our raw universe but filtered to bad_markets (might be reconsiderable)
filtered = bad & rob_jumbo
print(f"\n{'=' * 60}")
print(f"BAD_MARKETS but in Rob's jumbo (worth reconsidering?):")
print(f"{'=' * 60}")
for inst in sorted(filtered):
    print(f"  {inst}")

# 6. Detailed classification of gap
print(f"\n{'=' * 60}")
print("Gap breakdown by likely asset class")
print(f"{'=' * 60}")
# Parse our download_databento.py INSTRUMENTS to get Databento symbol mapping
mapping = dict(re.findall(r'"([A-Za-z][A-Za-z0-9_\-]+)":\s*"([A-Za-z0-9\.\-_]+)"', m2.group(1)))
for inst in sorted(gap):
    ticker = mapping.get(inst, "?")
    print(f"  {inst:<15s}  Databento ticker: {ticker}")
