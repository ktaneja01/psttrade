"""Fix Databento filenames where single-digit year parsing produced wrong years.

The downloader misparsed symbols like 'ALIF0' (Feb 2020) as year 0 (= 2000).
This script reads each CSV, inspects actual timestamps, and renames the file
to the correct YYYYMM based on the month encoded in the filename and the year
inferred from the data.

For each file Hour_{INSTRUMENT}_{YYYYMM}00.csv:
  1. Read the data, get the median timestamp
  2. The month in the filename (MM) is the expiration month — leave as-is
  3. The year should be ~= median_year or median_year + 1
     (contracts trade ~3-12 months before expiration)
"""
from pathlib import Path
import pandas as pd
import re

DATADIR = Path("/Users/kunal.taneja/pysystemtrade/data/databento/hourly")

# For each month letter, the expiration is typically in that month
MONTH_CODES = {
    "F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
    "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12,
}


def infer_correct_year(file_path: Path, filename_month: int) -> int:
    """Read the CSV, find the median data year, then add 0 or 1 year if the
    data is from the year preceding expiration."""
    try:
        df = pd.read_csv(file_path, nrows=5000, usecols=["Time"])
    except Exception:
        return None
    if len(df) == 0:
        return None

    # Parse timestamps
    ts = pd.to_datetime(df["Time"], format="%Y-%m-%dT%H:%M:%S%z", errors="coerce").dropna()
    if len(ts) == 0:
        return None

    # Contracts trade mostly in the months leading up to expiration.
    # The last observed timestamp's year is almost always the expiration year
    # (or very close to it). Use the MAX timestamp's year as the expiration year.
    # If filename month is >= last data month, it's the same year.
    # If filename month < last data month, it's the following year.
    last = ts.max()
    data_year = last.year
    data_month = last.month

    if data_month <= filename_month:
        return data_year
    else:
        return data_year + 1


def main():
    pattern = re.compile(r"^Hour_(.+)_(\d{4})(\d{2})00\.csv$")
    fixes = []
    unchanged = 0
    errors = 0

    for path in sorted(DATADIR.glob("Hour_*.csv")):
        m = pattern.match(path.name)
        if not m:
            continue
        inst, year_str, month_str = m.group(1), m.group(2), m.group(3)
        orig_year = int(year_str)
        month_num = int(month_str)

        # Only fix files whose year looks suspicious (0000-0009 → 2020-2029)
        # Actually inspect every file and correct if needed
        correct_year = infer_correct_year(path, month_num)
        if correct_year is None:
            errors += 1
            continue

        if correct_year == orig_year:
            unchanged += 1
            continue

        new_name = f"Hour_{inst}_{correct_year:04d}{month_num:02d}00.csv"
        new_path = path.parent / new_name
        if new_path.exists():
            # Conflict — another file already has the correct name
            # Keep the one with more data
            old_size = path.stat().st_size
            new_size = new_path.stat().st_size
            if old_size > new_size:
                new_path.unlink()
                path.rename(new_path)
            else:
                path.unlink()
        else:
            path.rename(new_path)
        fixes.append((path.name, new_name))

    print(f"Renamed: {len(fixes)} files")
    print(f"Unchanged: {unchanged}")
    print(f"Errors: {errors}")
    if fixes[:5]:
        print("\nFirst 5 renames:")
        for old, new in fixes[:5]:
            print(f"  {old} → {new}")


if __name__ == "__main__":
    main()
