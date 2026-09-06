"""Stage 2 — build curated roll-adjusted series from raw, reproducibly.

Reads raw hourly CSVs from data/raw/<INST>/, runs Carver's SHIPPED chain
(init contract prices -> derive daily from hourly -> build_and_write_roll_calendar
-> process_multiple_prices -> process_adjusted_prices), truncates every series at
the cutoff, and writes the curated store to data/curated_rolladjusted/.

The parquet DB backend is pointed at the curated store via a temporary
private_config edit (restored on exit). Deterministic: same raw -> same curated.

Designed to reproduce the 2018-2025 store that produced SR 0.474 (250K) / 0.602
(500K). After this, run 03_roll_audit and 04_data_quality_gate to validate.

Run:  pst-env/bin/python3 production/backtest/02_curate_rolladjusted.py
"""
import os, glob, shutil, re, json
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
os.chdir(ROOT)
CFG = json.load(open(os.path.join(HERE, "config.json")))
RAW = os.path.join(HERE, "data", "raw")
CUR = os.path.join(HERE, "data", "curated_rolladjusted")
WORK = "/tmp/ibkr_curate_work"   # DOT-FREE build path (parquet resolver turns dots->slashes; the repo path has a dot in kunal.taneja)
RC = os.path.join(HERE, "roll_calendars")   # repo copy (final)
RC_WORK = "/tmp/ibkr_rc_work"   # DOT-FREE build path for build_and_write_roll_calendar
CUTOFF = pd.Timestamp(CFG["window"]["cutoff"] + " 23:59:59") if CFG["window"].get("cutoff") else pd.Timestamp.now()
os.makedirs(RC, exist_ok=True); os.makedirs(RC_WORK, exist_ok=True)

PC = "private/private_config.yaml"
_orig = open(PC).read()
open(PC, "w").write(re.sub(r"parquet_store:.*", f"parquet_store: '{WORK}'", _orig))
try:
    from syscore.dateutils import HOURLY_FREQ, DAILY_PRICE_FREQ, MIXED_FREQ
    from sysdata.csv.csv_futures_contract_prices import ConfigCsvFuturesPrices
    from sysinit.futures.contract_prices_from_csv_to_db import init_db_with_csv_futures_contract_prices_for_code
    from sysinit.futures.rollcalendars_from_db_prices_to_csv import build_and_write_roll_calendar
    from sysinit.futures.multipleprices_from_db_prices_and_csv_calendars_to_db import process_multiple_prices_single_instrument
    from sysinit.futures.adjustedprices_from_db_multiple_to_db import process_adjusted_prices_single_instrument
    from sysproduction.data.prices import diagPrices

    lc = CFG["loader"]
    csv_cfg = ConfigCsvFuturesPrices(
        input_date_index_name=lc["date_index"], input_date_format=lc["date_format"],
        input_column_mapping=dict(lc["column_map"]))
    diag = diagPrices(); dbp = diag.db_futures_contract_price_data
    for sub in ["futures_contract_prices","futures_multiple_prices","futures_adjusted_prices"]:
        os.makedirs(os.path.join(WORK, sub), exist_ok=True)
    ADJ = os.path.join(WORK, "futures_adjusted_prices")
    MULT = os.path.join(WORK, "futures_multiple_prices")

    results = {}
    for inst in CFG["universe"]:
        try:
            repo_src = os.path.join(RAW, inst)
            csvs = glob.glob(f"{repo_src}/Hour_{inst}_*.csv")
            if not csvs:
                results[inst] = "NO RAW"; print(f"  {inst:15s} NO RAW"); continue
            # init_db resolves datapaths as PACKAGE paths -> the dot in kunal.taneja
            # breaks it (0 files, silent). Stage to a DOT-FREE dir before reading.
            src_dir = f"/tmp/ibkr_curate_stage/{inst}"
            shutil.rmtree(src_dir, ignore_errors=True); os.makedirs(src_dir)
            for f in csvs:
                shutil.copy(f, src_dir)
            for freq in [HOURLY_FREQ, DAILY_PRICE_FREQ, MIXED_FREQ]:
                try:
                    dbp.delete_prices_at_frequency_for_instrument_code(
                        instrument_code=inst, frequency=freq, areyousure=True)
                except Exception:
                    pass
            init_db_with_csv_futures_contract_prices_for_code(inst, src_dir, csv_config=csv_cfg, frequency=HOURLY_FREQ)
            # derive daily from hourly (last obs per date) + write MIXED
            cs = [c for c in dbp.get_contracts_with_price_data_for_frequency(HOURLY_FREQ)
                  if c.instrument_code == inst]
            for c in cs:
                h = dbp.get_prices_at_frequency_for_contract_object(c, frequency=HOURLY_FREQ)
                if len(h) == 0:
                    continue
                g = h.groupby(h.index.date)
                daily = h.loc[list(g.apply(lambda x: x.index[-1]).values)]
                if len(daily):
                    dbp.write_prices_at_frequency_for_contract_object(
                        c, futures_price_data=daily, ignore_duplication=True, frequency=DAILY_PRICE_FREQ)
                dbp.write_prices_at_frequency_for_contract_object(
                    c, futures_price_data=h, ignore_duplication=True, frequency=MIXED_FREQ)
            # roll calendar (Carver) + multiple + adjusted
            for f in [f"{RC_WORK}/{inst}.csv", f"{RC}/{inst}.csv", f"data/futures/roll_calendars_csv/{inst}.csv"]:
                if os.path.exists(f):
                    os.remove(f)
            build_and_write_roll_calendar(inst, output_datapath=RC_WORK, check_before_writing=False)
            shutil.copy(f"{RC_WORK}/{inst}.csv", f"data/futures/roll_calendars_csv/{inst}.csv")
            shutil.copy(f"{RC_WORK}/{inst}.csv", f"{RC}/{inst}.csv")
            process_multiple_prices_single_instrument(inst, ADD_TO_DB=True, ADD_TO_CSV=False)
            process_adjusted_prices_single_instrument(inst, ADD_TO_DB=True, ADD_TO_CSV=False)
            # truncate curated series at cutoff (uniform right edge)
            for D in [ADJ, MULT]:
                p = f"{D}/{inst}.parquet"
                if os.path.exists(p):
                    df = pd.read_parquet(p); df.index = pd.to_datetime(df.index)
                    df[df.index <= CUTOFF].to_parquet(p)
            a = pd.to_numeric(pd.read_parquet(f"{ADJ}/{inst}.parquet").iloc[:, 0], errors="coerce") \
                  .dropna().resample("1B").last().dropna()
            lm = a[a.diff() != 0].index.max()
            results[inst] = (str(a.index.min().date()), str(a.index.max().date()), str(lm.date()))
            print(f"  {inst:15s} OK {a.index.min().date()}..{a.index.max().date()} last_move={lm.date()}")
        except Exception as e:
            results[inst] = "ERR:" + str(e)[:60]; print(f"  {inst:15s} ERR {str(e)[:70]}")

    ok = sum(1 for v in results.values() if isinstance(v, tuple))
    json.dump({k: (list(v) if isinstance(v, tuple) else v) for k, v in results.items()},
              open(os.path.join(HERE, "artifacts", "curate_report.json"), "w"), indent=2)
    # copy the dot-free work store into the repo curated folder
    import subprocess
    for sub in ["futures_contract_prices","futures_multiple_prices","futures_adjusted_prices"]:
        subprocess.run(["rsync","-a","--delete",f"{WORK}/{sub}/",f"{CUR}/{sub}/"],check=True)
    print(f"\nCURATED {ok}/{len(CFG['universe'])} -> {CUR} (built in {WORK})")
    fails = {k: v for k, v in results.items() if not isinstance(v, tuple)}
    if fails:
        print("FAILURES:", fails)
finally:
    open(PC, "w").write(_orig)
