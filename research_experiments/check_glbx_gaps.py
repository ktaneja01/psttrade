"""Identify Rob jumbo instruments NOT downloaded and flag likely-GLBX candidates.

Tests Databento's GLBX.MDP3 by attempting to resolve common-pattern root symbols
for each missing instrument. Resolution = instrument IS on GLBX.
"""
import os, re, sys
from pathlib import Path
import databento as db

ROOT = Path("/Users/kunal.taneja/pysystemtrade")

# Rob's jumbo instrument set
rob_cfg = (ROOT / "systems/provided/rob_system/config.yaml").read_text()
m = re.search(r"^forecast_weights:\s*\n(.+?)\n^\w", rob_cfg, re.MULTILINE | re.DOTALL)
rob_jumbo = set(re.findall(r"^  ([A-Z][A-Z0-9_\-]+):\s*$", m.group(1), re.MULTILINE))

# Our downloads
dl = (ROOT / "download_databento.py").read_text()
m2 = re.search(r"INSTRUMENTS\s*=\s*\{(.+?)\n\}", dl, re.DOTALL)
our_downloads = set(re.findall(r'"([A-Za-z][A-Za-z0-9_\-]+)":', m2.group(1)))

# Rob's jumbo NOT downloaded
not_downloaded = sorted(rob_jumbo - our_downloads)
print(f"Rob's jumbo NOT in our downloads: {len(not_downloaded)}")

# Pre-known asset class / exchange hints (non-GLBX filters)
# These are instruments we KNOW are on non-CME exchanges — exclude from GLBX check
NON_GLBX_HINTS = {
    # Eurex (European bonds, equity)
    "BUND", "BOBL", "SHATZ", "BUXL", "OAT", "BTP", "BTP3", "CH10", "EURIBOR",
    "EUROSTX", "EUROSTX-LARGE", "EUROSTX-SMALL", "EUROSTX200-LARGE",
    "DAX", "AEX", "AEX_mini", "SMI", "SMI-MID", "OMX", "MIB",
    # ICE (Brent, cocoa, coffee, cotton, FX)
    "BRENT_CRUDE", "COCOA", "COFFEE", "COTTON", "COTTON2", "SUGAR11", "SUGAR16",
    "GASOIL", "WHEAT_ICE", "DX", "ICEFTSE", "V2X", "FTSE100", "FTSE250",
    # Cboe
    "VIX",
    # LME
    "TIN_LME", "SWISSLEAD",
    # ASX, Osaka, KRX, etc.
    "ASX", "JGB", "JGB-mini", "JGB-SGX-mini", "NIKKEI-JPY", "KOSPI",
    "HANG", "NIFTY", "TAIEX", "KR3", "KR10", "SGX",
    # Other regional
    "BONO", "BOVESPA", "FTSEINDO", "FTSEVIET", "RUR", "CLP", "CZK",
    "EPRA-EUROPE", "GICS", "HIGHYIELD", "HOUSE-US", "IG", "IRS",
    "JP-REALESTATE", "MSCIWORLD", "MSCIWORLDNET-EUR", "VNKI", "PL",
    "RUSSELL-MICRO", "MICRO",
    # EU sector DJ indices (STOXX)
    "EU-CHEM", "EU-MEDIA", "EU-RETAIL", "EU-TRAVEL", "EU-DJ-OIL",
    "EU-DJ-TECH", "EU-DJ-TELECOM", "EU-HOUSE", "EU-MID", "EU-UTIL",
    "DJSTX-SMALL",
    # Rates swaps (ICE/LSEG)
    "USIRS10", "USIRS2ERIS", "USIRS5", "USIRS5ERIS", "SONIA3",
    # Yen/Swiss bonds (not GLBX)
    "SARONA", "YENEUR",
    # Sector ETF-style
    "30YRCONF", "30YRJUMBO", "BB3M", "KR3", "FED-30", "MXWO", "US-UTIL",
}

candidates = [i for i in not_downloaded if i not in NON_GLBX_HINTS]
print(f"After filtering known non-GLBX: {len(candidates)} candidates")

# Now test each candidate against GLBX via Databento
client = db.Historical(key=os.environ["DATABENTO_API_KEY"])

# Common root-symbol patterns to try for each candidate
COMMON_PATTERNS = {
    # Known CME FX codes
    "NOK": ["6N", "NOK"],  # 6N is actually NZD; NOK might not be on CME
    "SEK": ["6S", "SEK"],  # 6S is CHF
    "SGD": ["SGD"],
    "TWD": ["TWD"],
    "CNH-onshore": [],  # not CME
    "CAD_micro": ["M6C"],
    "CHF_micro": ["M6S"],
    "GBP_micro": ["M6B"],
    "EURCAD": ["ECD", "RJ"],
    "EURAUD": ["EAD", "RL"],
    "GBPCHF": ["RP"],
    "GBPJPY": ["RY"],
    "AUDJPY": ["ANG"],
    "CHFJPY": ["RF"],
    "KRWUSD": [],
    "PLN": ["PLN"],
    "BRE": ["6L"],
    "RUR": [],
    "AUDUSD": ["6A"],
    "SP400": ["EMD"],
    "BOVESPA": [],
    "COAL": ["QL"],
    "COAL-GEORDIE": [],
    "COPPER-mini": ["QC"],
    "CORN_mini": ["YC"],
    "SOYBEAN_mini": ["YK"],
    "WHEAT_mini": ["YW"],
    "GAS-PEN": ["HP"],
    "BRENT-LAST": ["BB"],
    "ETHANOL": ["ZK", "EH"],
    "BRR": ["BRR"],
}

print(f"\n{'=' * 70}")
print("Testing candidate symbols against GLBX.MDP3...")
print(f"{'=' * 70}")

resolved = []
unresolved = []
no_pattern = []

for inst in candidates:
    patterns = COMMON_PATTERNS.get(inst)
    if patterns is None or len(patterns) == 0:
        no_pattern.append(inst)
        continue

    for pat in patterns:
        try:
            data = client.timeseries.get_range(
                dataset="GLBX.MDP3", symbols=[f"{pat}.FUT"], stype_in="parent",
                schema="ohlcv-1h", start="2024-01-01", end="2024-02-01",
            )
            df = data.to_df()
            if not df.empty:
                print(f"  ✓ {inst:15s} → {pat}.FUT  ({len(df)} rows)")
                resolved.append((inst, pat, len(df)))
                break
            else:
                continue
        except Exception as e:
            if "Could not resolve" in str(e):
                continue
            else:
                print(f"  ERROR {inst} → {pat}: {str(e)[:80]}")
                break
    else:
        unresolved.append(inst)
        print(f"  ✗ {inst:15s} (tried {patterns})")

print(f"\n{'=' * 70}")
print(f"SUMMARY")
print(f"{'=' * 70}")
print(f"Resolved on GLBX: {len(resolved)}")
for inst, pat, n in resolved:
    print(f"  {inst:20s} → {pat}.FUT ({n} rows in test window)")
print(f"\nNot on GLBX or symbol unknown: {len(unresolved)}")
print(f"\nNo pattern tried: {len(no_pattern)}")
for i in no_pattern[:20]:
    print(f"  {i}")
