"""Fetch specific missing Dec/Nov grain contracts directly (single-digit year bug fix)."""
import os, sys
from pathlib import Path
import pandas as pd
import databento as db

api_key = os.environ.get("DATABENTO_API_KEY")
if not api_key:
    sys.exit("DATABENTO_API_KEY not set")

OUTDIR = Path("/Users/kunal.taneja/pysystemtrade/data/databento/hourly")
client = db.Historical(key=api_key)

# (databento_symbol, pysystemtrade_instrument, year, month)
TARGETS = [
    ("ZWZ4", "WHEAT",   2024, 12),
    ("ZWZ5", "WHEAT",   2025, 12),
    ("ZWZ6", "WHEAT",   2026, 12),
    ("ZCZ4", "CORN",    2024, 12),
    ("ZCZ5", "CORN",    2025, 12),
    ("ZCZ6", "CORN",    2026, 12),
    ("ZSX5", "SOYBEAN", 2025, 11),
    ("ZSX6", "SOYBEAN", 2026, 11),
]

for sym, inst, year, month in TARGETS:
    print(f"\nFetching {sym} → {inst} {year}-{month:02d}")
    try:
        data = client.timeseries.get_range(
            dataset="GLBX.MDP3",
            symbols=[sym],
            stype_in="raw_symbol",
            schema="ohlcv-1h",
            start=f"{year - 3}-01-01",
            end=f"{year}-12-31",
        )
        df = data.to_df()
        if df.empty:
            print("  No data")
            continue
        print(f"  Got {len(df)} rows, {df.index[0]} to {df.index[-1]}")

        fname = OUTDIR / f"Hour_{inst}_{year}{month:02d}00.csv"
        out = pd.DataFrame({
            "Time": df.index.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "Open": df["open"],
            "High": df["high"],
            "Low": df["low"],
            "Latest": df["close"],
            "Volume": df["volume"].astype(int),
        })
        out["Time"] = out["Time"].str.replace(r"\+0000$", "+0000", regex=True)
        out.to_csv(fname, index=False)
        print(f"  Wrote {fname.name}")
    except Exception as e:
        print(f"  ERROR: {e}")
