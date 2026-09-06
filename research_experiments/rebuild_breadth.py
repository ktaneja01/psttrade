"""Rebuild the 13 bc-utils breadth instruments into adjusted prices.
Same verified pipeline as reingest_rebuild.py, sourcing from ~/data/barchart:
  stage+tz-strip -> init hourly -> derive daily -> roll calendar -> multiple -> adjusted.
Per-instrument try/except so one failure doesn't abort the batch.
"""
import os, glob, shutil, sys, pandas as pd
from syscore.dateutils import HOURLY_FREQ, DAILY_PRICE_FREQ, MIXED_FREQ
from sysdata.csv.csv_futures_contract_prices import ConfigCsvFuturesPrices
from sysinit.futures.contract_prices_from_csv_to_db import init_db_with_csv_futures_contract_prices_for_code
from sysinit.futures.rollcalendars_from_db_prices_to_csv import build_and_write_roll_calendar
from sysinit.futures.multipleprices_from_db_prices_and_csv_calendars_to_db import process_multiple_prices_single_instrument
from sysinit.futures.adjustedprices_from_db_multiple_to_db import process_adjusted_prices_single_instrument
from sysproduction.data.prices import diagPrices

TARGETS = sys.argv[1:] or ["EU-BANKS","EU-DJ-UTIL","EU-INSURE","EU-BASIC","US-REALESTATE",
    "FTSECHINAA","FTSECHINAH","MSCIWORLD","EUROSTX-SMALL","MSCISING","IRON","RUBBER","CANOLA"]

SRC = os.path.expanduser("~/data/barchart")
STAGE = "/tmp/breadth_hourly"; os.makedirs(STAGE, exist_ok=True)
os.makedirs("/tmp/roll_calendars", exist_ok=True)
ADJ_DIR = "/usr/local/bc_data/futures_adjusted_prices"
MULT_DIR = "/usr/local/bc_data/futures_multiple_prices"

CFG = ConfigCsvFuturesPrices(input_date_index_name="Time", input_date_format="%Y-%m-%dT%H:%M:%S",
    input_skiprows=0, input_skipfooter=0,
    input_column_mapping=dict(OPEN="Open", HIGH="High", LOW="Low", FINAL="Latest", VOLUME="Volume"))

diag = diagPrices(); dbp = diag.db_futures_contract_price_data
results = {}
for inst in TARGETS:
    try:
        # purge any prior DB contracts for a clean re-init
        for freq in [HOURLY_FREQ, DAILY_PRICE_FREQ, MIXED_FREQ]:
            try: dbp.delete_prices_at_frequency_for_instrument_code(instrument_code=inst, frequency=freq, areyousure=True)
            except Exception: pass
        # stage + tz-strip
        for old in glob.glob(f"{STAGE}/Hour_{inst}_*.csv"): os.remove(old)
        csvs = glob.glob(f"{SRC}/Hour_{inst}_*.csv")
        if not csvs:
            results[inst] = ("NO SOURCE CSVs", 0); print(f"{inst:16s} NO SOURCE CSVs", flush=True); continue
        for f in csvs:
            open(f"{STAGE}/{os.path.basename(f)}", "w").write(open(f).read().replace("+0000", ""))
        init_db_with_csv_futures_contract_prices_for_code(inst, STAGE, csv_config=CFG, frequency=HOURLY_FREQ)
        # derive daily from hourly (last per date) + write MIXED
        cs = [c for c in dbp.get_contracts_with_price_data_for_frequency(HOURLY_FREQ) if c.instrument_code == inst]
        for c in cs:
            h = dbp.get_prices_at_frequency_for_contract_object(c, frequency=HOURLY_FREQ)
            if len(h) == 0: continue
            g = h.groupby(h.index.date); daily = h.loc[list(g.apply(lambda x: x.index[-1]).values)]
            if len(daily): dbp.write_prices_at_frequency_for_contract_object(c, futures_price_data=daily, ignore_duplication=True, frequency=DAILY_PRICE_FREQ)
            dbp.write_prices_at_frequency_for_contract_object(c, futures_price_data=h, ignore_duplication=True, frequency=MIXED_FREQ)
        # fresh roll calendar + rebuild
        for f in [f"/tmp/roll_calendars/{inst}.csv", f"data/futures/roll_calendars_csv/{inst}.csv",
                  f"{MULT_DIR}/{inst}.parquet", f"{ADJ_DIR}/{inst}.parquet"]:
            if os.path.exists(f): os.remove(f)
        build_and_write_roll_calendar(inst, output_datapath="/tmp/roll_calendars", check_before_writing=False)
        shutil.copy(f"/tmp/roll_calendars/{inst}.csv", f"data/futures/roll_calendars_csv/{inst}.csv")
        process_multiple_prices_single_instrument(inst, ADD_TO_DB=True, ADD_TO_CSV=False)
        process_adjusted_prices_single_instrument(inst, ADD_TO_DB=True, ADD_TO_CSV=False)
        adj = pd.to_numeric(pd.read_parquet(f"{ADJ_DIR}/{inst}.parquet").iloc[:,0], errors="coerce").dropna().resample("1B").last().dropna()
        lm = adj[adj.diff() != 0].index.max()
        results[inst] = (f"{adj.index.min().date()}..{adj.index.max().date()}", len(adj), lm.date())
        print(f"{inst:16s} {adj.index.min().date()}..{adj.index.max().date()}  n={len(adj)}  last_move={lm.date()}", flush=True)
    except Exception as e:
        results[inst] = ("ERROR", str(e)[:80]); print(f"{inst:16s} ERROR {str(e)[:100]}", flush=True)

print("\n===== SUMMARY =====", flush=True)
for i, v in results.items(): print(f"  {i:16s} {v}", flush=True)
