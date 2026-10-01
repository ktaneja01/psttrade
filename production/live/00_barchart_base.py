"""Stage 0b — build a Barchart historical base for given instruments directly into
the LIVE curated store, and wire them into config.json. Makes `live` self-contained
(no research-seed dependency): Barchart base here -> 01_fetch_ibkr + 03_append bring
it current.

For each instrument:
  1. stage ~/data/barchart/Hour_<INST>_*.csv, tz-strip the Time column, into
     production/live/data/raw/<INST>/ (permanent raw, so IB append extends it later)
     and a DOT-FREE /tmp stage (the parquet/csv path resolver breaks on the '.' in the
     home dir -> 0 files, silently).
  2. Carver's shipped chain on a DOT-FREE work store: init hourly contract prices ->
     derive daily (last obs/day) + MIXED -> build_and_write_roll_calendar ->
     process_multiple -> process_adjusted.
  3. copy ONLY this instrument's contract/multiple/adjusted parquet into the live
     curated store (never --delete; other instruments untouched).
Then add the instruments to config.json universe + ib_contract_map (from the shipped
ib_config_futures.csv). Idempotent: re-running rebuilds cleanly from the same raw.

Run:  pst-env/bin/python3 production/live/00_barchart_base.py [INST ...]
      default: EURIBOR SONIA3 WHEAT
"""
import os, glob, shutil, re, json, sys, csv
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
os.chdir(ROOT)
CFG = json.load(open(os.path.join(HERE, "config.json")))
BARCHART = os.path.expanduser("~/data/barchart")
RAW = os.path.join(HERE, "data", "raw")
CUR = os.path.join(HERE, "data", "curated_rolladjusted")
WORK = "/tmp/bc_base_work"          # dot-free build store
STAGE = "/tmp/bc_base_stage"        # dot-free init_db source
RC_WORK = "/tmp/bc_base_rc"         # dot-free roll-calendar output
LIVE_RC = os.path.join(HERE, "roll_calendars")
SHIP_IB = os.path.join(ROOT, "sysbrokers", "IB", "config", "ib_config_futures.csv")
CUTOFF = pd.Timestamp(CFG["window"]["cutoff"] + " 23:59:59") if CFG["window"].get("cutoff") else pd.Timestamp.now()
INSTS = sys.argv[1:] or ["EURIBOR", "SONIA3", "WHEAT"]

for d in [RAW, CUR, RC_WORK, LIVE_RC, STAGE]:
    os.makedirs(d, exist_ok=True)
for sub in ["futures_contract_prices", "futures_multiple_prices", "futures_adjusted_prices"]:
    os.makedirs(os.path.join(WORK, sub), exist_ok=True)
    os.makedirs(os.path.join(CUR, sub), exist_ok=True)

lc = CFG["loader"]

import re as _re
def _decode_cbot_frac(v):
    """CBOT grain tick notation 'XXX-Y' (Y = eighths of a cent, e.g. 725-2 = 725.25)
    -> decimal. Core-api returns grains in this format; working grains (REDWHEAT/CORN)
    store decimal cents, so decode to match. Passthrough for already-decimal values."""
    m = _re.match(r'^(-?\d+)-(\d+)$', str(v).strip())
    return float(m.group(1)) + float(m.group(2)) / 8.0 if m else v

def stage_raw(inst):
    """tz-strip barchart raw -> permanent live raw + dot-free /tmp stage. Returns #files."""
    files = sorted(glob.glob(f"{BARCHART}/Hour_{inst}_*.csv"))
    if not files:
        return 0
    dest_repo = os.path.join(RAW, inst)
    dest_stage = os.path.join(STAGE, inst)
    os.makedirs(dest_repo, exist_ok=True)
    shutil.rmtree(dest_stage, ignore_errors=True); os.makedirs(dest_stage)
    tzcol = lc["date_index"]
    for f in files:
        df = pd.read_csv(f)
        if tzcol in df.columns:                       # strip +0000 / any [+-]HHMM tz suffix
            df[tzcol] = df[tzcol].astype(str).str.replace(r"[+-]\d{4}$", "", regex=True)
        # coerce price/volume cols to numeric so the reader's `*= price_magnifier`
        # (csv_futures_contract_prices.py:104) doesn't hit an object/string column
        # (core-api EOD emits blanks for N/A -> object dtype -> "*100.0" TypeError on WHEAT)
        for c in [lc["column_map"][k] for k in ["OPEN", "HIGH", "LOW", "FINAL"]]:
            if c in df.columns:
                df[c] = df[c].map(_decode_cbot_frac)     # CBOT grain 'XXX-Y' -> decimal
        for c in [lc["column_map"][k] for k in ["OPEN", "HIGH", "LOW", "FINAL", "VOLUME"]]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=[lc["column_map"]["FINAL"]])
        base = os.path.basename(f)
        df.to_csv(os.path.join(dest_repo, base), index=False)
        df.to_csv(os.path.join(dest_stage, base), index=False)
    return len(files)

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
            n = stage_raw(inst)
            if n == 0:
                results[inst] = "NO BARCHART RAW"; print(f"  {inst:10s} NO BARCHART RAW"); continue
            src_dir = os.path.join(STAGE, inst)
            # clean any prior prices for this inst in the work store
            for freq in [HOURLY_FREQ, DAILY_PRICE_FREQ, MIXED_FREQ]:
                try:
                    dbp.delete_prices_at_frequency_for_instrument_code(
                        instrument_code=inst, frequency=freq, areyousure=True)
                except Exception:
                    pass
            for p in glob.glob(f"{CONT}/{inst}#*.parquet"):
                os.remove(p)
            init_db_with_csv_futures_contract_prices_for_code(inst, src_dir, csv_config=csv_cfg, frequency=HOURLY_FREQ)
            # derive daily (last obs/day) + write MIXED
            cs = [c for c in dbp.get_contracts_with_price_data_for_frequency(HOURLY_FREQ)
                  if c.instrument_code == inst]
            for c in cs:
                h = dbp.get_prices_at_frequency_for_contract_object(c, frequency=HOURLY_FREQ)
                if len(h) == 0:
                    continue
                g = h.groupby(h.index.date)
                daily = h.loc[list(g.apply(lambda x: x.index[-1]).values)]
                # FREQUENCY-SEAM FIX: floor derived-daily to 00:00 so hourly and EOD
                # contracts share a timestamp -> roll builder always matches concurrent
                # prices across a hourly/EOD seam. Write MIXED from the aligned daily too.
                daily.index = pd.to_datetime(daily.index).normalize()
                if len(daily):
                    dbp.write_prices_at_frequency_for_contract_object(
                        c, futures_price_data=daily, ignore_duplication=True, frequency=DAILY_PRICE_FREQ)
                dbp.write_prices_at_frequency_for_contract_object(
                    c, futures_price_data=daily, ignore_duplication=True, frequency=MIXED_FREQ)
            # roll calendar + multiple + adjusted
            for f in [f"{RC_WORK}/{inst}.csv", f"{LIVE_RC}/{inst}.csv", f"data/futures/roll_calendars_csv/{inst}.csv"]:
                if os.path.exists(f):
                    os.remove(f)
            build_and_write_roll_calendar(inst, output_datapath=RC_WORK, check_before_writing=False)
            shutil.copy(f"{RC_WORK}/{inst}.csv", f"data/futures/roll_calendars_csv/{inst}.csv")
            shutil.copy(f"{RC_WORK}/{inst}.csv", f"{LIVE_RC}/{inst}.csv")
            process_multiple_prices_single_instrument(inst, csv_roll_data_path=RC_WORK, ADD_TO_DB=True, ADD_TO_CSV=False)
            process_adjusted_prices_single_instrument(inst, ADD_TO_DB=True, ADD_TO_CSV=False)
            # truncate at cutoff, copy ONLY this inst into live curated
            for sub, D in [("futures_adjusted_prices", ADJ), ("futures_multiple_prices", MULT)]:
                p = f"{D}/{inst}.parquet"
                if os.path.exists(p):
                    df = pd.read_parquet(p); df.index = pd.to_datetime(df.index)
                    df[df.index <= CUTOFF].to_parquet(p)
            for sub in ["futures_contract_prices", "futures_multiple_prices", "futures_adjusted_prices"]:
                for p in glob.glob(f"{WORK}/{sub}/{inst}*.parquet"):
                    shutil.copy(p, f"{CUR}/{sub}/{os.path.basename(p)}")
            a = pd.to_numeric(pd.read_parquet(f"{ADJ}/{inst}.parquet").iloc[:, 0], errors="coerce") \
                  .dropna().resample("1B").last().dropna()
            lm = a[a.diff() != 0].index.max()
            results[inst] = (str(a.index.min().date()), str(a.index.max().date()), str(lm.date()), n)
            print(f"  {inst:10s} OK {a.index.min().date()}..{a.index.max().date()} last_move={lm.date()} ({n} raw files)")
        except Exception as e:
            import traceback
            results[inst] = "ERR:" + str(e)[:80]; print(f"  {inst:10s} ERR {str(e)[:90]}")
            traceback.print_exc()
finally:
    open(PC, "w").write(_orig)

# ---- wire config.json: add to universe + ib_contract_map (additive, idempotent) ----
built = [i for i in INSTS if isinstance(results.get(i), tuple)]
if built:
    shutil.copy(os.path.join(HERE, "config.json"), os.path.join(HERE, "config.json.bak3"))
    ib_ship = {}
    with open(SHIP_IB) as fh:
        for row in csv.DictReader(fh):
            ib_ship[row["Instrument"]] = row
    for inst in built:
        if inst not in CFG["universe"]:
            CFG["universe"].append(inst)
        r = ib_ship.get(inst)
        if r and inst not in CFG["ib_contract_map"]:
            CFG["ib_contract_map"][inst] = {
                "symbol": r["IBSymbol"], "exchange": r["IBExchange"],
                "currency": r["IBCurrency"] if r["IBCurrency"] not in ("NA", "") else "nan",
                "multiplier": str(float(r["IBMultiplier"])),
                "price_magnifier": float(r["priceMagnifier"]),
                "ignore_weekly": r["IgnoreWeekly"].strip().upper() == "TRUE"}
    json.dump(CFG, open(os.path.join(HERE, "config.json"), "w"), indent=2)
    print(f"\nwired into config.json (backup config.json.bak3): +{built} to universe ({len(CFG['universe'])}) + ib_contract_map")

json.dump({k: (list(v) if isinstance(v, tuple) else v) for k, v in results.items()},
          open(os.path.join(HERE, "artifacts", "barchart_base_report.json"), "w"), indent=2)
ok = sum(1 for v in results.values() if isinstance(v, tuple))
print(f"\nBARCHART BASE {ok}/{len(INSTS)} built -> {CUR}")
fails = {k: v for k, v in results.items() if not isinstance(v, tuple)}
if fails:
    print("FAILURES:", fails)
