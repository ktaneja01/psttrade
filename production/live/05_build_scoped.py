"""Scoped, non-destructive build from the MERGED live raw (Barchart base + IB tail).

Reads production/live/data/raw/<INST>/ (which 00_barchart_base seeded from Barchart
and 01_fetch_ibkr extended with IB contracts), runs the shipped Carver chain, and
copies ONLY the given instruments' contract/multiple/adjusted parquet into the live
curated store. Unlike 02_curate it does not iterate the whole universe and never
--deletes the store.

Run:  pst-env/bin/python3 production/live/05_build_scoped.py INST [INST ...]
"""
import os, glob, shutil, re, json, sys
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
os.chdir(ROOT)
CFG = json.load(open(os.path.join(HERE, "config.json")))
RAW = os.path.join(HERE, "data", "raw")
CUR = os.path.join(HERE, "data", "curated_rolladjusted")
WORK = "/tmp/bc_scoped_work"; STAGE = "/tmp/bc_scoped_stage"; RC_WORK = "/tmp/bc_scoped_rc"
LIVE_RC = os.path.join(HERE, "roll_calendars")
CUTOFF = pd.Timestamp(CFG["window"]["cutoff"] + " 23:59:59") if CFG["window"].get("cutoff") else pd.Timestamp.now()
INSTS = sys.argv[1:]
if not INSTS:
    print("usage: 05_build_scoped.py INST [INST ...]"); sys.exit(2)

import re as _re
def _decode_cbot_frac(v):
    """CBOT grain tick 'XXX-Y' (Y eighths, e.g. 725-2=725.25) -> decimal; passthrough else."""
    m = _re.match(r'^(-?\d+)-(\d+)$', str(v).strip())
    return float(m.group(1)) + float(m.group(2)) / 8.0 if m else v

for d in [RC_WORK, LIVE_RC, STAGE]:
    os.makedirs(d, exist_ok=True)
for sub in ["futures_contract_prices", "futures_multiple_prices", "futures_adjusted_prices"]:
    os.makedirs(os.path.join(WORK, sub), exist_ok=True)
    os.makedirs(os.path.join(CUR, sub), exist_ok=True)
lc = CFG["loader"]

PC = "private/private_config.yaml"
_orig = open(PC).read()
open(PC, "w").write(re.sub(r"parquet_store:.*", f"parquet_store: '{WORK}'", _orig))
results = {}
try:
    from syscore.dateutils import HOURLY_FREQ, DAILY_PRICE_FREQ, MIXED_FREQ
    from sysdata.csv.csv_futures_contract_prices import ConfigCsvFuturesPrices
    from sysinit.futures.contract_prices_from_csv_to_db import init_db_with_csv_futures_contract_prices_for_code
    from sysinit.futures.rollcalendars_from_db_prices_to_csv import build_and_write_roll_calendar
    from sysinit.futures.multipleprices_from_db_prices_and_csv_calendars_to_db import process_multiple_prices_single_instrument
    from sysinit.futures.adjustedprices_from_db_multiple_to_db import process_adjusted_prices_single_instrument
    from sysproduction.data.prices import diagPrices

    csv_cfg = ConfigCsvFuturesPrices(
        input_date_index_name=lc["date_index"], input_date_format=lc["date_format"],
        input_column_mapping=dict(lc["column_map"]))
    diag = diagPrices(); dbp = diag.db_futures_contract_price_data
    ADJ = os.path.join(WORK, "futures_adjusted_prices")
    MULT = os.path.join(WORK, "futures_multiple_prices")
    CONT = os.path.join(WORK, "futures_contract_prices")

    for inst in INSTS:
        try:
            csvs = sorted(glob.glob(f"{RAW}/{inst}/Hour_{inst}_*.csv"))
            if not csvs:
                results[inst] = "NO LIVE RAW"; print(f"  {inst:10s} NO LIVE RAW"); continue
            # dot-free stage with defensive tz-strip + numeric coercion
            src_dir = os.path.join(STAGE, inst)
            shutil.rmtree(src_dir, ignore_errors=True); os.makedirs(src_dir)
            for f in csvs:
                df = pd.read_csv(f)
                if lc["date_index"] in df.columns:
                    df[lc["date_index"]] = df[lc["date_index"]].astype(str).str.replace(r"[+-]\d{4}$", "", regex=True)
                for c in [lc["column_map"][k] for k in ["OPEN", "HIGH", "LOW", "FINAL"]]:
                    if c in df.columns:
                        df[c] = df[c].map(_decode_cbot_frac)
                for c in [lc["column_map"][k] for k in ["OPEN", "HIGH", "LOW", "FINAL", "VOLUME"]]:
                    if c in df.columns:
                        df[c] = pd.to_numeric(df[c], errors="coerce")
                df = df.dropna(subset=[lc["column_map"]["FINAL"]])
                df.to_csv(os.path.join(src_dir, os.path.basename(f)), index=False)
            for freq in [HOURLY_FREQ, DAILY_PRICE_FREQ, MIXED_FREQ]:
                try:
                    dbp.delete_prices_at_frequency_for_instrument_code(instrument_code=inst, frequency=freq, areyousure=True)
                except Exception:
                    pass
            for p in glob.glob(f"{CONT}/{inst}#*.parquet"):
                os.remove(p)
            init_db_with_csv_futures_contract_prices_for_code(inst, src_dir, csv_config=csv_cfg, frequency=HOURLY_FREQ)
            cs = [c for c in dbp.get_contracts_with_price_data_for_frequency(HOURLY_FREQ) if c.instrument_code == inst]
            for c in cs:
                h = dbp.get_prices_at_frequency_for_contract_object(c, frequency=HOURLY_FREQ)
                if len(h) == 0:
                    continue
                g = h.groupby(h.index.date)
                daily = h.loc[list(g.apply(lambda x: x.index[-1]).values)]
                # FREQUENCY-SEAM FIX: floor derived-daily to 00:00 so hourly and EOD
                # contracts share a timestamp -> roll builder can always match concurrent
                # prices across a hourly/EOD seam. Write MIXED from the aligned daily too.
                daily.index = pd.to_datetime(daily.index).normalize()
                if len(daily):
                    dbp.write_prices_at_frequency_for_contract_object(c, futures_price_data=daily, ignore_duplication=True, frequency=DAILY_PRICE_FREQ)
                dbp.write_prices_at_frequency_for_contract_object(c, futures_price_data=daily, ignore_duplication=True, frequency=MIXED_FREQ)
            for f in [f"{RC_WORK}/{inst}.csv", f"{LIVE_RC}/{inst}.csv", f"data/futures/roll_calendars_csv/{inst}.csv"]:
                if os.path.exists(f):
                    os.remove(f)
            build_and_write_roll_calendar(inst, output_datapath=RC_WORK, check_before_writing=False)
            shutil.copy(f"{RC_WORK}/{inst}.csv", f"data/futures/roll_calendars_csv/{inst}.csv")
            shutil.copy(f"{RC_WORK}/{inst}.csv", f"{LIVE_RC}/{inst}.csv")
            process_multiple_prices_single_instrument(inst, csv_roll_data_path=RC_WORK, ADD_TO_DB=True, ADD_TO_CSV=False)
            process_adjusted_prices_single_instrument(inst, ADD_TO_DB=True, ADD_TO_CSV=False)
            for D in [ADJ, MULT]:
                p = f"{D}/{inst}.parquet"
                if os.path.exists(p):
                    df = pd.read_parquet(p); df.index = pd.to_datetime(df.index)
                    df[df.index <= CUTOFF].to_parquet(p)
            for sub in ["futures_contract_prices", "futures_multiple_prices", "futures_adjusted_prices"]:
                for p in glob.glob(f"{WORK}/{sub}/{inst}*.parquet"):
                    shutil.copy(p, f"{CUR}/{sub}/{os.path.basename(p)}")
            a = pd.to_numeric(pd.read_parquet(f"{ADJ}/{inst}.parquet").iloc[:, 0], errors="coerce").dropna().resample("1B").last().dropna()
            lm = a[a.diff() != 0].index.max()
            rc = pd.read_csv(f"{LIVE_RC}/{inst}.csv")
            results[inst] = (str(a.index.min().date()), str(a.index.max().date()),
                             str(lm.date()) if pd.notna(lm) else None, len(csvs), len(rc))
            print(f"  {inst:10s} OK {a.index.min().date()}..{a.index.max().date()} last_move={lm.date() if pd.notna(lm) else None} "
                  f"({len(csvs)} raw files, {len(rc)} roll rows)")
        except Exception as e:
            import traceback
            results[inst] = "ERR:" + str(e)[:80]; print(f"  {inst:10s} ERR {str(e)[:90]}"); traceback.print_exc()
finally:
    open(PC, "w").write(_orig)

json.dump({k: (list(v) if isinstance(v, tuple) else v) for k, v in results.items()},
          open(os.path.join(HERE, "artifacts", "build_scoped_report.json"), "w"), indent=2)
ok = sum(1 for v in results.values() if isinstance(v, tuple))
print(f"\nSCOPED BUILD {ok}/{len(INSTS)} -> {CUR}")
