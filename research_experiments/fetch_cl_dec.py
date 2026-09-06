"""Try fetching specific CLZ December contracts directly."""
import os, sys
import databento as db

api_key = os.environ.get("DATABENTO_API_KEY")
if not api_key:
    sys.exit("DATABENTO_API_KEY not set")

client = db.Historical(key=api_key)

# Try different symbol formats for Dec 2023
for sym in ["CLZ23", "CLZ3", "CL.Z23", "CL.FUT"]:
    try:
        print(f"\n=== Trying {sym} ===")
        stype = "parent" if sym == "CL.FUT" else "raw_symbol"
        data = client.timeseries.get_range(
            dataset="GLBX.MDP3",
            symbols=[sym],
            stype_in=stype,
            schema="ohlcv-1h",
            start="2022-01-01",
            end="2024-01-01",
        )
        df = data.to_df()
        if "symbol" in df.columns:
            counts = df["symbol"].value_counts()
            print(f"  rows: {len(df)}")
            dec_syms = [s for s in counts.index if "Z23" in s or "Z3" in s]
            print(f"  Dec-2023-ish symbols: {dec_syms[:10]}")
            if len(dec_syms):
                for d in dec_syms[:3]:
                    print(f"    {d}: {counts[d]} rows")
        else:
            print(f"  rows: {len(df)}, columns: {list(df.columns)}")
    except Exception as e:
        print(f"  ERROR: {e}")
