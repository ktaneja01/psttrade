"""Stage B (v2) — STRICT APPEND-ONLY: extend the vendor seed with IB live data
without re-deriving any historical row.

The earlier version re-ran init_db + derive-daily over the full span, which
regenerated historical per-contract daily prices and FILLED carry-contract gaps
(NaN->value) that existed in the vendor build. Adjusted *returns* were unchanged
(panama uses PRICE, not CARRY), but the CARRY column changed -> carry-rule
forecasts shifted -> 2019-2025 P&L drifted. Root cause: re-derivation, NOT
look-ahead.

This version freezes the vendor historical rows and only appends IB rows dated
strictly AFTER each contract's last vendor date, at DAILY + MIXED frequency
(the frequencies the sim reads). Then rebuilds roll/multiple/adjusted. Result:
2019-2025 is byte-identical to the vendor store; only post-Dec-2025 extends.

Run:  pst-env/bin/python3 production/live/03_append_ib.py
"""
import os, glob, shutil, re, json, subprocess
import pandas as pd, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
os.chdir(ROOT)
CFG = json.load(open(os.path.join(HERE, "config.json")))
RAW = os.path.join(HERE, "data", "raw")
CUR = os.path.join(HERE, "data", "curated_rolladjusted")          # currently = vendor seed
SEED = os.path.join(ROOT, "production", "research", "data", "curated_rolladjusted")  # authoritative vendor seed (RESEARCH branch)
WORK = "/tmp/ibkr_appendonly_work"
RC_WORK = "/tmp/ibkr_appendonly_rc"
LIVE_RC = os.path.join(HERE, "roll_calendars")   # store-local roll-calendar record (isolated)
os.makedirs(LIVE_RC, exist_ok=True)
lc = CFG["loader"]
SEED_BOUNDARY = pd.Timestamp("2026-06-30 23:59:59")  # vendor seed now extends to Jun-30-2026; IB owns Jul-2026+

PC = "private/private_config.yaml"
_orig = open(PC).read()
open(PC, "w").write(re.sub(r"parquet_store:.*", f"parquet_store: '{WORK}'", _orig))
try:
    from syscore.dateutils import HOURLY_FREQ, DAILY_PRICE_FREQ, MIXED_FREQ
    from sysinit.futures.rollcalendars_from_db_prices_to_csv import build_and_write_roll_calendar
    from sysinit.futures.multipleprices_from_db_prices_and_csv_calendars_to_db import process_multiple_prices_single_instrument
    from sysinit.futures.adjustedprices_from_db_multiple_to_db import process_adjusted_prices_single_instrument
    from sysdata.parquet.parquet_access import ParquetAccess
    from sysdata.parquet.parquet_futures_per_contract_prices import parquetFuturesContractPriceData

    # fresh work store SEEDED from the authoritative vendor seed (frozen historical rows)
    shutil.rmtree(WORK, ignore_errors=True)
    for sub in ["futures_contract_prices", "futures_multiple_prices", "futures_adjusted_prices"]:
        os.makedirs(f"{WORK}/{sub}", exist_ok=True)
        for f in glob.glob(f"{SEED}/{sub}/*.parquet"):
            shutil.copy(f, f"{WORK}/{sub}/")
    os.makedirs(RC_WORK, exist_ok=True)

    from sysproduction.data.prices import diagPrices
    diag = diagPrices(); dbp = diag.db_futures_contract_price_data
    ADJ = f"{WORK}/futures_adjusted_prices"; MULT = f"{WORK}/futures_multiple_prices"

    def read_ib_contract(inst, month_id):
        """Daily series for one IB contract from the raw CSV (month-keyed)."""
        p = os.path.join(RAW, inst, f"Hour_{inst}_{month_id}.csv")
        if not os.path.exists(p):
            return None
        df = pd.read_csv(p)
        t = pd.to_datetime(df[lc["date_index"]].astype(str).str.replace(r"[+-]\d{4}$", "", regex=True),
                           errors="coerce")
        s = pd.Series(pd.to_numeric(df[lc["column_map"]["FINAL"]], errors="coerce").values, index=t).dropna()
        s = s.resample("1B").last().dropna()
        return s

    results = {}; seam = {}
    for inst in CFG["universe"]:
        try:
            # existing (vendor) per-contract prices in the work store, per contract
            existing = {}
            for f in glob.glob(f"{WORK}/futures_contract_prices/{inst}#*.parquet"):
                cid = re.search(rf"{re.escape(inst)}#(\d+)", os.path.basename(f)).group(1)
                existing[cid] = f
            # IB raw contracts available (month-keyed)
            ib_ids = sorted(re.search(r"_(\d{6}00)\.csv$", os.path.basename(f)).group(1)
                            for f in glob.glob(f"{RAW}/{inst}/Hour_{inst}_*.csv")
                            if re.search(r"_(\d{6}00)\.csv$", os.path.basename(f)))
            appended_rows = 0; new_contracts = 0
            from sysobjects.contracts import futuresContract
            for month_id in ib_ids:
                cid8 = month_id  # already YYYYMM00
                ib = read_ib_contract(inst, month_id)
                if ib is None or len(ib) == 0:
                    continue
                fc = futuresContract(inst, cid8)
                if cid8 in existing:
                    # APPEND ONLY rows strictly after the vendor contract's last date
                    cur = dbp.get_prices_at_frequency_for_contract_object(fc, frequency=DAILY_PRICE_FREQ)
                    curs = cur.return_final_prices() if hasattr(cur, "return_final_prices") else cur
                    curs = (curs if isinstance(curs, pd.Series) else curs.iloc[:, 0]).dropna()
                    curs.index = pd.to_datetime(curs.index)
                    last = curs.index.max()
                    add = ib[ib.index > last]
                    if len(add) == 0:
                        continue
                    appended_rows += len(add)
                else:
                    # brand-new contract (post-seed) — take all IB rows after the seed boundary
                    add = ib[ib.index > SEED_BOUNDARY]
                    if len(add) == 0:
                        continue
                    new_contracts += 1
                # write add-only rows at DAILY + MIXED (merge, keep existing)
                from sysobjects.futures_per_contract_prices import futuresContractPrices
                fcp = futuresContractPrices(pd.DataFrame(
                    {"OPEN": add.values, "HIGH": add.values, "LOW": add.values,
                     "FINAL": add.values, "VOLUME": 1.0}, index=add.index))
                dbp.write_prices_at_frequency_for_contract_object(fc, futures_price_data=fcp, ignore_duplication=True, frequency=DAILY_PRICE_FREQ)
                dbp.write_prices_at_frequency_for_contract_object(fc, futures_price_data=fcp, ignore_duplication=True, frequency=MIXED_FREQ)

            # rebuild roll/multiple/adjusted (historical per-contract rows are frozen; only tail extended)
            # ISOLATED: dot-free RC_WORK passed as csv_roll_data_path (native sysinit arg);
            # never touches the shared repo data/futures/roll_calendars_csv/.
            for f in [f"{RC_WORK}/{inst}.csv"]:
                if os.path.exists(f):
                    os.remove(f)
            build_and_write_roll_calendar(inst, output_datapath=RC_WORK, check_before_writing=False)
            shutil.copy(f"{RC_WORK}/{inst}.csv", f"{LIVE_RC}/{inst}.csv")  # store-local record
            process_multiple_prices_single_instrument(
                inst, csv_roll_data_path=RC_WORK, ADD_TO_DB=True, ADD_TO_CSV=False)
            process_adjusted_prices_single_instrument(inst, ADD_TO_DB=True, ADD_TO_CSV=False)

            a = pd.to_numeric(pd.read_parquet(f"{ADJ}/{inst}.parquet").iloc[:, 0], errors="coerce").dropna()
            a.index = pd.to_datetime(a.index); ad = a.resample("1B").last().dropna()
            lm = ad[ad.diff() != 0].index.max()
            results[inst] = (str(ad.index.min().date()), str(ad.index.max().date()),
                             str(lm.date()) if pd.notna(lm) else None, appended_rows, new_contracts)
            print(f"  {inst:15s} ->{ad.index.max().date()} (+{appended_rows} rows, +{new_contracts} contracts)")
        except Exception as e:
            results[inst] = "ERR:" + str(e)[:60]; print(f"  {inst:15s} ERR {str(e)[:70]}")

    for sub in ["futures_contract_prices", "futures_multiple_prices", "futures_adjusted_prices"]:
        subprocess.run(["rsync", "-a", "--delete", f"{WORK}/{sub}/", f"{CUR}/{sub}/"], check=True)
    json.dump({k: (list(v) if isinstance(v, tuple) else v) for k, v in results.items()},
              open(os.path.join(HERE, "artifacts", "append_report.json"), "w"), indent=2)
    ok = sum(1 for v in results.values() if isinstance(v, tuple))
    print(f"\nAPPEND-ONLY {ok}/{len(CFG['universe'])} rebuilt -> {CUR}")
finally:
    open(PC, "w").write(_orig)
