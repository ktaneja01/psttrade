"""Fetch the missing Dec CL contracts (CLZ3, CLZ4, CLZ5) directly by symbol."""
import os, sys
from pathlib import Path
import pandas as pd
import databento as db

api_key = os.environ.get("DATABENTO_API_KEY")
if not api_key:
    sys.exit("DATABENTO_API_KEY not set")

OUTDIR = Path("/Users/kunal.taneja/pysystemtrade/data/databento/hourly")
client = db.Historical(key=api_key)

# Target contracts: Dec 2023, Dec 2024, Dec 2025
TARGETS = {
    "CLZ3": 2023,
    "CLZ4": 2024,
    "CLZ5": 2025,
}

for symbol, year in TARGETS.items():
    print(f"\n=== Fetching {symbol} (Dec {year}) ===")
    try:
        data = client.timeseries.get_range(
            dataset="GLBX.MDP3",
            symbols=[symbol],
            stype_in="raw_symbol",
            schema="ohlcv-1h",
            start=f"{year - 3}-01-01",  # contract trades ~3 yrs before expiry
            end=f"{year}-12-31",
        )
        df = data.to_df()
        if df.empty:
            print(f"  No data returned")
            continue
        print(f"  Got {len(df)} rows, {df.index[0]} to {df.index[-1]}")

        # Write in bc-utils format
        fname = OUTDIR / f"Hour_CRUDE_W_{year}1200.csv"
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
        print(f"  Wrote {fname}")
    except Exception as e:
        print(f"  ERROR: {e}")
