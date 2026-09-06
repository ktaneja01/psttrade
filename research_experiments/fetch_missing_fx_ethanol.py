"""Fetch PLN, BRE, INR, ETHANOL, ALUMINIUM via parent symbology with explicit retry."""
import os, sys
from pathlib import Path
import pandas as pd
import databento as db
from download_databento import parse_contract_symbol, MONTH_CODES, load_priced_cycles

api_key = os.environ.get("DATABENTO_API_KEY")
client = db.Historical(key=api_key)
OUTDIR = Path("/Users/kunal.taneja/pysystemtrade/data/databento/hourly")
priced_cycles = load_priced_cycles()

# (pysystemtrade_code, databento_root)
TARGETS = [
    ("PLN",       "WP"),
    ("BRE",       "L6"),
    ("INR",       "H3"),
    ("ETHANOL",   "ZK"),
    ("ALUMINIUM", "ALI"),
]

for inst, root in TARGETS:
    cycle = priced_cycles.get(inst, "FGHJKMNQUVXZ")
    print(f"\n=== {inst} ({root}, cycle={cycle}) ===")
    try:
        data = client.timeseries.get_range(
            dataset="GLBX.MDP3",
            symbols=[f"{root}.FUT"],
            stype_in="parent",
            schema="ohlcv-1h",
            start="2015-01-01",
            end="2026-04-19",
        )
        df = data.to_df()
    except Exception as e:
        print(f"  ERROR: {e}")
        continue

    if df.empty:
        print("  empty")
        continue
    print(f"  Got {len(df)} rows, {df['symbol'].nunique()} symbols")

    allowed = set(cycle)
    written = 0
    skipped = 0
    for contract_symbol, sub in df.groupby("symbol"):
        month_letter, year = parse_contract_symbol(contract_symbol, root)
        if month_letter is None:
            skipped += 1
            continue
        if month_letter not in allowed:
            skipped += 1
            continue
        month_num = MONTH_CODES[month_letter]
        fname = OUTDIR / f"Hour_{inst}_{year:04d}{month_num:02d}00.csv"
        out = pd.DataFrame({
            "Time": sub.index.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "Open": sub["open"], "High": sub["high"], "Low": sub["low"],
            "Latest": sub["close"], "Volume": sub["volume"].astype(int),
        })
        out["Time"] = out["Time"].str.replace(r"\+0000$", "+0000", regex=True)
        out.to_csv(fname, index=False)
        written += 1
    print(f"  Wrote {written} contracts (skipped {skipped})")
