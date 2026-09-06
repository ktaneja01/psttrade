"""Download 5 new CME FX crosses and run full pipeline."""
import os, sys
from pathlib import Path
import pandas as pd
import databento as db
from download_databento import parse_contract_symbol, MONTH_CODES

client = db.Historical(key=os.environ["DATABENTO_API_KEY"])
OUTDIR = Path("/Users/kunal.taneja/pysystemtrade/data/databento/hourly")

# (pysystemtrade_code, databento_root, priced_roll_cycle)
# CME FX crosses roll quarterly (HMUZ), similar to their majors
TARGETS = [
    ("GBPJPY", "RY",  "HMUZ"),
    ("EURCAD", "ECD", "HMUZ"),
    ("EURAUD", "EAD", "HMUZ"),
    ("AUDJPY", "AJY", "HMUZ"),
    ("CHFJPY", "SJY", "HMUZ"),
]

for inst, root, cycle in TARGETS:
    print(f"\n=== {inst} ({root}.FUT, cycle={cycle}) ===")
    try:
        data = client.timeseries.get_range(
            dataset="GLBX.MDP3", symbols=[f"{root}.FUT"], stype_in="parent",
            schema="ohlcv-1h", start="2015-01-01", end="2026-04-19",
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
    for contract_symbol, sub in df.groupby("symbol"):
        month_letter, year = parse_contract_symbol(contract_symbol, root)
        if month_letter is None or month_letter not in allowed:
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
    print(f"  Wrote {written} contracts")
