"""Re-download CRUDE_W only (to fix 2017-2019 data gaps)."""
import os, sys
import databento as db
from download_databento import (
    INSTRUMENTS, load_priced_cycles, download_instrument,
    DATASET, SCHEMA, START_DATE, END_DATE, OUTDIR,
)

api_key = os.environ.get("DATABENTO_API_KEY")
if not api_key:
    print("ERROR: DATABENTO_API_KEY not set", file=sys.stderr)
    sys.exit(1)

client = db.Historical(key=api_key)
priced_cycles = load_priced_cycles()

code = "CRUDE_W"
root = INSTRUMENTS[code]
cycle = priced_cycles[code]

print(f"Re-downloading {code} ({root}), cycle={cycle}")
print(f"Window: {START_DATE} → {END_DATE}")
print(f"Output: {OUTDIR}")

n = download_instrument(code, root, client, cycle)
print(f"\nWrote {n} contracts")
