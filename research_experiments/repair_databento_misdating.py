"""One-time repair for the Databento single-digit-year contract mis-dating bug.

Databento recycles single-digit year codes every decade (e.g. `HEG5` = Feb-2015
AND Feb-2025), so the old symbol-parse mis-dated contracts, scrambling the stored
per-contract parquet (phantom 200X files, multi-year blobs). The fix (in
download_databento.download_instrument) now groups by instrument_id and dates each
contract from its OWN data timestamps.

Per instrument: purge DB + parquet + roll calendar -> re-download (fixed) ->
stage (tz-strip) -> init hourly -> derive daily -> roll calendar -> multiple ->
adjusted -> preflight. Resilient: one failure doesn't abort the batch.

Run:  source .databento.env && python repair_databento_misdating.py [INSTR ...]
"""
import os, sys, shutil, glob
import pandas as pd
import databento as db

import download_databento as dd
dd.END_DATE = "2026-08-18"   # GLBX available up to 2026-08-18 (avoid 422)

from syscore.dateutils import HOURLY_FREQ, DAILY_PRICE_FREQ, MIXED_FREQ
from sysdata.csv.csv_futures_contract_prices import ConfigCsvFuturesPrices
from sysinit.futures.contract_prices_from_csv_to_db import init_db_with_csv_futures_contract_prices_for_code
from sysinit.futures.rollcalendars_from_db_prices_to_csv import build_and_write_roll_calendar
from sysinit.futures.multipleprices_from_db_prices_and_csv_calendars_to_db import process_multiple_prices_single_instrument
from sysinit.futures.adjustedprices_from_db_multiple_to_db import process_adjusted_prices_single_instrument
from sysproduction.data.prices import diagPrices

# affected Databento CME names (LEANHOG already repaired & validated separately)
AFFECTED = ["AUD","BITCOIN","CHF","CRUDE_W","ETHEREUM","EUR","FEEDCOW","GBP","JPY",
            "LIVECOW","MXP","NIKKEI","NZD","RICE","RUSSELL","SILVER","SOYBEAN",
            "SOYMEAL","SP500","US10","US30","WHEAT","ZAR"]
if len(sys.argv) > 1:
    AFFECTED = sys.argv[1:]

STAGE = "/tmp/databento_hourly"
os.makedirs(STAGE, exist_ok=True)
os.makedirs("/tmp/roll_calendars", exist_ok=True)
CFG = ConfigCsvFuturesPrices(
    input_date_index_name="Time", input_date_format="%Y-%m-%dT%H:%M:%S",
    input_skiprows=0, input_skipfooter=0,
    input_column_mapping=dict(OPEN="Open", HIGH="High", LOW="Low",
                              FINAL="Latest", VOLUME="Volume"),
)
client = db.Historical(key=os.environ["DATABENTO_API_KEY"])
cycles = dd.load_priced_cycles()
diag = diagPrices(); dbp = diag.db_futures_contract_price_data
symmap = {k: v for k, v in dd.INSTRUMENTS.items()}


def preflight(inst):
    p = f"/usr/local/bc_data/futures_adjusted_prices/{inst}.parquet"
    if not os.path.exists(p): return "NO ADJUSTED FILE"
    s = pd.to_numeric(pd.read_parquet(p).iloc[:, 0], errors="coerce").dropna()
    s = s.resample("1B").last().dropna()
    if len(s) < 200: return f"THIN ({len(s)}d)"
    r = s.pct_change().abs()
    bad = int((r > 0.20).sum())
    return (f"{s.index.min().date()}..{s.index.max().date()} n={len(s)} "
            f"moves>20%={bad} {'CLEAN' if bad == 0 else 'CORRUPT'}")


results = {}
for i, inst in enumerate(AFFECTED, 1):
    print(f"\n{'='*66}\n[{i}/{len(AFFECTED)}] {inst}\n{'='*66}", flush=True)
    try:
        root = symmap[inst]
        # 1. purge DB + parquet + roll calendar
        for freq in [HOURLY_FREQ, DAILY_PRICE_FREQ, MIXED_FREQ]:
            try: dbp.delete_prices_at_frequency_for_instrument_code(instrument_code=inst, frequency=freq, areyousure=True)
            except Exception: pass
        for pq in [f"/usr/local/bc_data/futures_multiple_prices/{inst}.parquet",
                   f"/usr/local/bc_data/futures_adjusted_prices/{inst}.parquet"]:
            if os.path.exists(pq): os.remove(pq)
        for rc in [f"/tmp/roll_calendars/{inst}.csv", f"data/futures/roll_calendars_csv/{inst}.csv"]:
            if os.path.exists(rc): os.remove(rc)

        # 2. re-download (fixed parser), clearing old CSVs first
        for old in glob.glob(f"data/databento/hourly/Hour_{inst}_*.csv"): os.remove(old)
        n = dd.download_instrument(inst, root, client, cycles[inst])
        if n == 0:
            results[inst] = "DOWNLOAD 0 CONTRACTS"; print("  !! 0 contracts"); continue

        # 3. stage with tz-strip
        for old in glob.glob(f"{STAGE}/Hour_{inst}_*.csv"): os.remove(old)
        for f in glob.glob(f"data/databento/hourly/Hour_{inst}_*.csv"):
            with open(f) as r: data = r.read().replace("+0000", "")
            with open(f"{STAGE}/{os.path.basename(f)}", "w") as w: w.write(data)

        # 4. init hourly -> daily
        init_db_with_csv_futures_contract_prices_for_code(inst, STAGE, csv_config=CFG, frequency=HOURLY_FREQ)
        contracts = [c for c in dbp.get_contracts_with_price_data_for_frequency(HOURLY_FREQ) if c.instrument_code == inst]
        for c in contracts:
            hourly = dbp.get_prices_at_frequency_for_contract_object(c, frequency=HOURLY_FREQ)
            if len(hourly) == 0: continue
            grp = hourly.groupby(hourly.index.date)
            daily = hourly.loc[list(grp.apply(lambda g: g.index[-1]).values)]
            if len(daily): dbp.write_prices_at_frequency_for_contract_object(c, futures_price_data=daily, ignore_duplication=True, frequency=DAILY_PRICE_FREQ)
            dbp.write_prices_at_frequency_for_contract_object(c, futures_price_data=hourly, ignore_duplication=True, frequency=MIXED_FREQ)

        # 5. roll calendar -> multiple -> adjusted
        build_and_write_roll_calendar(inst, output_datapath="/tmp/roll_calendars", check_before_writing=False)
        src = f"/tmp/roll_calendars/{inst}.csv"; dst = f"data/futures/roll_calendars_csv/{inst}.csv"
        if os.path.exists(src): shutil.copy(src, dst)
        process_multiple_prices_single_instrument(inst, ADD_TO_DB=True, ADD_TO_CSV=False)
        process_adjusted_prices_single_instrument(inst, ADD_TO_DB=True, ADD_TO_CSV=False)

        results[inst] = preflight(inst)
        print(f"  -> {results[inst]}", flush=True)
    except Exception as e:
        results[inst] = f"ERROR: {str(e)[:100]}"
        print(f"  !! {results[inst]}", flush=True)

print(f"\n\n{'='*66}\nREPAIR SUMMARY\n{'='*66}")
for inst, r in results.items():
    print(f"  {inst:12s} {r}")
