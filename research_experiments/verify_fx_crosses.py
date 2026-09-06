"""Verify which CME root symbols map to which FX cross by checking currency attrs."""
import os
import databento as db
client = db.Historical(key=os.environ["DATABENTO_API_KEY"])

# CME published cross-currency futures (common codes)
CANDIDATES = {
    "RF":  "Euro FX / Swiss Franc (EURCHF?)",
    "RP":  "British Pound / Swiss Franc (GBPCHF)",
    "RY":  "British Pound / Japanese Yen (GBPJPY)",
    "ECD": "Euro FX / Canadian Dollar",
    "EAD": "Euro FX / Australian Dollar",
    "EGP": "Euro FX / British Pound",
    "AJY": "Australian Dollar / Japanese Yen",
    "CJY": "Canadian Dollar / Japanese Yen",
    "SJY": "Swiss Franc / Japanese Yen",
    "CSF": "Swiss Franc / Canadian Dollar",
    "CHFJPY": "alt symbol",
}

for code, desc in CANDIDATES.items():
    try:
        data = client.timeseries.get_range(
            dataset="GLBX.MDP3", symbols=[f"{code}.FUT"], stype_in="parent",
            schema="ohlcv-1h", start="2024-01-01", end="2024-02-01",
        )
        df = data.to_df()
        if df.empty:
            print(f"  {code:<8s} empty ({desc})")
        else:
            syms = df["symbol"].unique()
            print(f"  {code:<8s} OK - {len(df)} rows - symbols: {list(syms[:3])} ({desc})")
    except Exception as e:
        msg = str(e)
        if "Could not resolve" in msg:
            print(f"  {code:<8s} UNRESOLVED ({desc})")
        else:
            print(f"  {code:<8s} ERROR: {msg[:60]}")
